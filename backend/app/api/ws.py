"""WebSocket endpoint for extension / desktop connectivity."""

from __future__ import annotations

import json

from app.websocket.manager import ConnectionManager
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])


async def _send_connection_message(websocket: WebSocket) -> None:
    await websocket.send_json({"type": "connection", "status": "connected"})


async def _send_pong(websocket: WebSocket) -> None:
    await websocket.send_json({"type": "pong"})


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept a background connection and respond to ping frames.

    Each connection is registered in the per-user channel derived from the
    ``channel`` query parameter (defaults to ``"default"``).  The channel
    name is used by the webhook processor to broadcast incoming Messenger
    events to the right desktop / extension client.
    """
    channel: str = websocket.query_params.get("channel", "default")
    manager: ConnectionManager = websocket.app.state.manager

    await manager.connect(websocket, channel)
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
        manager.disconnect(websocket, channel)
