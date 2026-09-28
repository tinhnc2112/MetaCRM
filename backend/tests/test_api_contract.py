"""Keep the documented route table aligned with the registered application."""

import re
from pathlib import Path

from app.core.config import get_settings
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

CONTRACT = Path(__file__).resolve().parents[2] / "docs/architecture/api-contract.md"


def _registered() -> set[tuple[str, str]]:
    result = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/v1") or path == "/version":
            methods = getattr(route, "methods", None) or {"WS"}
            result.update((method, path) for method in methods)
    return result


def test_contract_lists_exactly_the_registered_application_routes() -> None:
    documented = set(
        re.findall(
            r"^\| (GET|POST|PUT|PATCH|DELETE|WS) \| `([^`]+)` \|", CONTRACT.read_text(), re.M
        )
    )
    assert documented == _registered()
    openapi = app.openapi()["paths"]
    assert {(method.upper(), path) for path, data in openapi.items() for method in data} == {
        item for item in _registered() if item[0] != "WS"
    }


def test_health_and_version_aliases_remain_public(monkeypatch) -> None:
    app.state.settings = get_settings()
    client = TestClient(app)
    assert client.get("/health").status_code == 404
    assert client.get("/api/v1/system/health").json() == {"status": "ok", "service": "metacrm-api"}
    assert client.get("/version").json() == client.get("/api/v1/system/version").json()

    monkeypatch.setattr("app.api.system.check_database_connection", lambda: None)
    assert client.get("/api/v1/system/health/database").status_code == 200

    def unavailable() -> None:
        raise SQLAlchemyError("test-only outage")

    monkeypatch.setattr("app.api.system.check_database_connection", unavailable)
    assert client.get("/api/v1/system/health/database").status_code == 503
