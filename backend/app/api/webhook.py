"""Facebook Messenger webhook verification and event receiver."""

from __future__ import annotations

import json
from typing import Annotated

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

    # -- 1. read raw body before JSON parsing ---------------------------------
    body = await request.body()

    # -- 2. signature verification --------------------------------------------
    if not settings.facebook_app_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Facebook App Secret is not configured",
        )

    signature_header = request.headers.get("X-Hub-Signature-256")
    try:
        verify_webhook_signature(body, signature_header, settings.facebook_app_secret)
    except FacebookWebhookSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    # -- 3. parse payload -----------------------------------------------------
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    # Facebook wraps all Messenger events under object="page"
    if payload.get("object") != "page":
        # Silently accept non-page object types (e.g. instagram) — return 200
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
