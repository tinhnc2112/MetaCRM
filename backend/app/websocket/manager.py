"""In-memory connection manager; replace or extend for multi-process fan-out."""

from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """Manage active WebSocket connections by named channel."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, channel: str = "default") -> None:
        await websocket.accept()
        self._connections[channel].add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str = "default") -> None:
        connections = self._connections.get(channel)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(channel, None)

    async def broadcast(self, message: str, channel: str = "default") -> None:
        """Send text to current subscribers; discard stale connections."""
        stale: list[WebSocket] = []
        for websocket in self._connections.get(channel, set()).copy():
            try:
                await websocket.send_text(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket, channel)
