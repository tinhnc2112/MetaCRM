"""Facebook Messenger webhook verification and event receiver."""

from __future__ import annotations

import json
import logging
from typing import Annotated
from uuid import uuid4

from app.core.config import get_settings
from app.db.session import get_db_session
from app.schemas.messenger import WebhookAcceptedResponse
from app.services.facebook.messenger import (
    FacebookWebhookSignatureError,
    parse_webhook_payload,
    process_webhook_events,
    verify_webhook_signature,
)
from app.websocket.manager import ConnectionManager
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)


async def read_and_log_webhook_request(
    request: Request,
) -> tuple[str, str | None, bytes]:
    """Read a request body and emit the common webhook ingress diagnostics."""
    # Client-supplied header values are untrusted, including request IDs and lengths.
    request_id = str(uuid4())
    signature_header = request.headers.get("X-Hub-Signature-256")
    logger.info(
        "facebook webhook POST received request_id=%s signature_present=%s",
        request_id,
        bool(signature_header),
    )
    body = await request.body()
    logger.info(
        "facebook webhook body read request_id=%s body_length=%d",
        request_id,
        len(body),
    )
    return request_id, signature_header, body


# ---------------------------------------------------------------------------
# GET — Facebook hub verification challenge
# ---------------------------------------------------------------------------


@router.get("")
def webhook_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> int:
    """Respond to Facebook's webhook verification handshake.

    Facebook sends ``hub.mode=subscribe``, ``hub.verify_token``, and
    ``hub.challenge``.  We confirm the token matches our config and echo
    the challenge back as a plain integer.
    """
    settings = get_settings()

    if hub_mode != "subscribe":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hub.mode must be 'subscribe'",
        )

    if not settings.facebook_webhook_verify_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook verify token is not configured",
        )

    if hub_verify_token != settings.facebook_webhook_verify_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="hub.verify_token does not match",
        )

    if not hub_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hub.challenge is missing",
        )

    return int(hub_challenge)


# ---------------------------------------------------------------------------
# POST — receive Messenger events
# ---------------------------------------------------------------------------

# Local replay for Postman:
# POST http://127.0.0.1:8000/api/v1/facebook/webhook


@router.post("", response_model=WebhookAcceptedResponse)
async def webhook_receive(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> WebhookAcceptedResponse:
    """Receive, verify, persist, and broadcast Facebook Messenger events.

    Steps:
    1. Read raw body (needed for HMAC verification).
    2. Verify X-Hub-Signature-256.
    3. Parse JSON payload into RawMessageEvent list.
    4. Persist new conversations/messages (idempotent by mid).
    5. Broadcast each new message to the relevant WebSocket channel.
    """
    settings = get_settings()
    request_id, signature_header, body = await read_and_log_webhook_request(request)

    # -- 2. signature verification --------------------------------------------
    if not settings.facebook_app_secret:
        logger.error(
            "facebook webhook signature verification failed request_id=%s reason=app_secret_not_configured",
            request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Facebook App Secret is not configured",
        )

    try:
        verify_webhook_signature(body, signature_header, settings.facebook_app_secret)
    except FacebookWebhookSignatureError as exc:
        logger.warning(
            "facebook webhook signature verification failed request_id=%s reason=%s",
            request_id,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    logger.info("facebook webhook signature verified request_id=%s", request_id)

    # -- 3. parse payload -----------------------------------------------------
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "facebook webhook JSON parsing failed request_id=%s body_length=%d error_type=%s",
            request_id,
            len(body),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    object_type = payload.get("object")
    entries = payload.get("entry")
    entry_count = len(entries) if isinstance(entries, list) else 0
    logger.info(
        "facebook webhook payload parsed request_id=%s is_page=%s entry_count=%d",
        request_id,
        object_type == "page",
        entry_count,
    )

    # Facebook wraps all Messenger events under object="page"
    if object_type != "page":
        logger.info("facebook webhook ignored reason=unsupported_object")
        return WebhookAcceptedResponse(received=True, events_processed=0)

    events = parse_webhook_payload(payload)

    # -- 4. persist -----------------------------------------------------------
    results = process_webhook_events(session, events)

    # -- 5. broadcast new messages via ConnectionManager ----------------------
    manager: ConnectionManager = request.app.state.manager
    for conversation, _message, was_created in results:
        if not was_created:
            continue  # duplicate — skip broadcast

        broadcast_payload = json.dumps(
            {
                "type": "new_message",
                "conversation_id": str(conversation.uuid),
            }
        )
        # Broadcast on the page-scoped channel so only the owning user's
        # desktop/extension receives the event
        await manager.broadcast(broadcast_payload, channel=f"page:{conversation.page_id}")

    return WebhookAcceptedResponse(received=True, events_processed=len(results))
