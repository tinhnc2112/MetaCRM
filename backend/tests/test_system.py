import pytest
from app.main import app
from fastapi import status
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "metacrm-api"}


def test_version() -> None:
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["version"]


def test_websocket_rejects_anonymous_connection() -> None:
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/ws") as websocket:
                websocket.receive_json()
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
