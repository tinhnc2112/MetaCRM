from fastapi.testclient import TestClient

from app.main import app


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


def test_websocket_connection_and_ping_pong() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/ws") as websocket:
            assert websocket.receive_json() == {"type": "connection", "status": "connected"}
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}
