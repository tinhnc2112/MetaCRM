"""WebSocket endpoint for extension / desktop connectivity."""

from __future__ import annotations

import json
from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import resolve_user_from_access_token
from app.services.facebook.exceptions import FacebookPageUnavailableError
from app.services.facebook.pages import get_page_for_user
from app.websocket.manager import ConnectionManager
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

router = APIRouter(tags=["websocket"])
_AUTH_SUBPROTOCOL = "metacrm"
_BEARER_SUBPROTOCOL_PREFIX = "bearer."


async def _send_connection_message(websocket: WebSocket) -> None:
    await websocket.send_json({"type": "connection", "status": "connected"})


async def _send_pong(websocket: WebSocket) -> None:
    await websocket.send_json({"type": "pong"})


async def _reject_connection(websocket: WebSocket) -> None:
    """Complete the handshake only to send a generic policy-violation close."""
    requested_protocols = _requested_subprotocols(websocket)
    selected_protocol = _AUTH_SUBPROTOCOL if _AUTH_SUBPROTOCOL in requested_protocols else None
    await websocket.accept(subprotocol=selected_protocol)
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)


def _requested_subprotocols(websocket: WebSocket) -> list[str]:
    header = websocket.headers.get("sec-websocket-protocol", "")
    return [item.strip() for item in header.split(",") if item.strip()]


def _extract_access_token(websocket: WebSocket) -> str | None:
    requested_protocols = _requested_subprotocols(websocket)
    if _AUTH_SUBPROTOCOL not in requested_protocols:
        return None
    bearer_protocols = [
        item for item in requested_protocols if item.startswith(_BEARER_SUBPROTOCOL_PREFIX)
    ]
    if len(bearer_protocols) != 1:
        return None
    token = bearer_protocols[0][len(_BEARER_SUBPROTOCOL_PREFIX) :]
    return token or None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    """Authorize a Page subscription, then register its server-derived channel."""
    access_token = _extract_access_token(websocket)
    page_id = websocket.query_params.get("page_id")

    # Raw channel names are no longer a supported client contract. Requiring
    # page_id keeps every subscription behind Page ownership authorization.
    if (
        "channel" in websocket.query_params
        or "access_token" in websocket.query_params
        or not access_token
        or not page_id
    ):
        await _reject_connection(websocket)
        return

    user = resolve_user_from_access_token(session, access_token)
    if user is None or not user.is_active:
        await _reject_connection(websocket)
        return

    try:
        page = get_page_for_user(session, user, page_id)
    except FacebookPageUnavailableError:
        await _reject_connection(websocket)
        return

    channel = f"page:{page.page_id}"
    manager: ConnectionManager = websocket.app.state.manager

    await manager.connect(websocket, channel, subprotocol=_AUTH_SUBPROTOCOL)
    await _send_connection_message(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            normalized = message.strip().lower()

            if normalized == "ping":
                await _send_pong(websocket)
                continue

            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue

            if isinstance(payload, dict) and str(payload.get("type", "")).lower() == "ping":
                await _send_pong(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, channel)
