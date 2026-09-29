"""M6 action authorization: role gates and a complete active-route inventory."""

from collections.abc import Generator

import pytest
from app.db.base import Base
from app.db.session import get_db_session
from app.dependencies.auth import require_active_user, require_admin
from app.main import app
from app.models.auth import Role, User
from app.services.facebook.auth import create_oauth_state
from app.utils.jwt import create_access_token
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def authorization_context(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add_all(
        [
            User(
                username=name,
                email=f"{name}@example.test",
                password_hash="unused",
                roles=[Role(name=role)] if role else [],
            )
            for name, role in [
                ("admin", "admin"),
                ("employee", "staff"),
                ("unassigned", None),
                ("manager", "manager"),
            ]
        ]
    )
    session.commit()
    monkeypatch.setattr("app.startup.lifecycle.init_db", lambda: None)

    def override_db() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_db
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def _headers(session: Session, name: str) -> dict[str, str]:
    user = session.query(User).filter(User.username == name).one()
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


ADMIN_OPERATIONS = {
    ("PUT", "/api/v1/publishing/config"),
    ("POST", "/api/v1/publishing/sync"),
    ("POST", "/api/v1/publishing/posts/{post_id}/resolve"),
    ("GET", "/api/v1/facebook/auth/url"),
    ("POST", "/api/v1/facebook/pages/sync"),
    *(
        ("GET", f"/api/v1/facebook/debug/{suffix}")
        for suffix in (
            "subscribed-apps/{page_id}",
            "token-scopes",
            "page-permissions/{page_id}",
            "page-info/{page_id}",
            "app-mode",
            "app-info",
            "webhook-subscriptions",
            "messenger-diagnostics",
            "page-token/{page_id}",
            "webhook-health",
        )
    ),
    ("POST", "/api/v1/facebook/debug/resubscribe/{page_id}"),
    ("POST", "/api/v1/facebook/debug/webhook-selftest"),
    *(
        ("POST", f"/api/v1/facebook/products/{{product_uuid}}/inventory/{action}")
        for action in ("enable", "disable", "adjustments")
    ),
    ("POST", "/api/v1/facebook/carrier-accounts"),
    ("PATCH", "/api/v1/facebook/carrier-accounts/{account_uuid}"),
    ("PUT", "/api/v1/facebook/carrier-accounts/{account_uuid}/credentials"),
    ("POST", "/api/v1/facebook/carrier-accounts/{account_uuid}/deactivate"),
}
PUBLIC_OPERATIONS = {
    ("GET", "/api/v1/system/health"),
    ("GET", "/api/v1/system/health/database"),
    ("GET", "/api/v1/system/version"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/facebook/webhook"),
    ("POST", "/api/v1/facebook/webhook"),
    ("GET", "/api/v1/facebook/auth/callback"),
}


def _dependencies(route: APIRoute) -> set[object]:
    def walk(node) -> set[object]:
        return {node.call} | set().union(*(walk(child) for child in node.dependencies))

    return walk(route.dependant)


def test_entire_active_route_surface_is_classified() -> None:
    protected = set()
    public = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1/"):
            continue
        operations = {(method, route.path) for method in route.methods}
        if operations.issubset(PUBLIC_OPERATIONS):
            public.update(operations)
            continue  # public monitoring, token lifecycle, signed provider flows
        deps = _dependencies(route)
        assert require_active_user in deps, route.path
        if require_admin in deps:
            protected.update(operations)
        else:
            assert operations.isdisjoint(ADMIN_OPERATIONS), route.path
            assert not route.path.startswith("/api/v1/facebook/debug/"), route.path
            assert not (
                route.path.startswith("/api/v1/facebook/carrier-accounts")
                and route.methods != {"GET"}
            ), route.path
            assert not ("/inventory" in route.path and route.methods != {"GET"}), route.path
            assert not (
                route.path.startswith("/api/v1/facebook/pages")
                and route.methods != {"GET"}
                and route.path != "/api/v1/facebook/pages/{page_id}/select"
            ), route.path
            assert route.path.startswith(
                (
                    "/api/v1/auth/me",
                    "/api/v1/facebook/pages",
                    "/api/v1/facebook/carriers/providers",
                    "/api/v1/facebook/carrier-accounts",
                    "/api/v1/facebook/products",
                    "/api/v1/facebook/conversations",
                    "/api/v1/facebook/customers",
                    "/api/v1/facebook/orders",
                    "/api/v1/facebook/shipments",
                    "/api/v1/facebook/customer-tags",
                    "/api/v1/facebook/segments",
                    "/api/v1/publishing/",
                )
            ), route.path
    assert protected == ADMIN_OPERATIONS
    assert public == PUBLIC_OPERATIONS


@pytest.mark.parametrize("method,path", sorted(ADMIN_OPERATIONS))
def test_employee_cannot_reach_admin_operation(
    authorization_context: tuple[TestClient, Session],
    method: str,
    path: str,
) -> None:
    client, session = authorization_context
    path = path.replace("{product_uuid}", "missing").replace("{account_uuid}", "missing")
    path = path.replace("{page_id}", "missing")
    response = client.request(method, path, headers=_headers(session, "employee"), json={})
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"
    admin = client.request(method, path, headers=_headers(session, "admin"), json={})
    assert admin.status_code != 403


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",
        "/api/v1/facebook/conversations",
        "/api/v1/facebook/customers",
        "/api/v1/facebook/orders",
        "/api/v1/facebook/products",
        "/api/v1/facebook/shipments/missing",
        "/api/v1/facebook/carriers/providers",
        "/api/v1/facebook/carrier-accounts",
        "/api/v1/facebook/pages",
        "/api/v1/facebook/products/missing/inventory",
    ],
)
def test_employee_and_admin_have_business_read_access(
    authorization_context: tuple[TestClient, Session],
    path: str,
) -> None:
    client, session = authorization_context
    for role in ("employee", "admin"):
        assert client.get(path, headers=_headers(session, role)).status_code != 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/facebook/products"),
        ("POST", "/api/v1/facebook/orders"),
        ("PATCH", "/api/v1/facebook/orders/missing"),
        ("POST", "/api/v1/facebook/customers/missing/notes"),
        ("POST", "/api/v1/facebook/conversations/missing/messages"),
        ("POST", "/api/v1/facebook/orders/missing/shipments"),
        ("PATCH", "/api/v1/facebook/shipments/missing/status"),
        ("POST", "/api/v1/facebook/conversations/missing/outbound-sends/123/reconcile"),
    ],
)
def test_employee_can_enter_business_write_operations(
    authorization_context: tuple[TestClient, Session],
    method: str,
    path: str,
) -> None:
    client, session = authorization_context
    assert (
        client.request(method, path, json={}, headers=_headers(session, "employee")).status_code
        != 403
    )


@pytest.mark.parametrize("name", ["unassigned", "manager"])
def test_unknown_or_unassigned_roles_fail_closed(
    authorization_context: tuple[TestClient, Session],
    name: str,
) -> None:
    client, session = authorization_context
    assert client.get("/api/v1/auth/me", headers=_headers(session, name)).status_code == 403


def test_revoked_role_takes_effect_with_existing_access_token(
    authorization_context: tuple[TestClient, Session],
) -> None:
    client, session = authorization_context
    headers = _headers(session, "admin")
    assert client.get("/api/v1/facebook/debug/webhook-health", headers=headers).status_code == 200
    user = session.query(User).filter(User.username == "admin").one()
    user.roles[0].is_active = False
    session.commit()
    assert client.get("/api/v1/facebook/debug/webhook-health", headers=headers).status_code == 403


def test_oauth_callback_rechecks_admin_before_graph_exchange(
    authorization_context: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = authorization_context
    employee = session.query(User).filter(User.username == "employee").one()
    state = create_oauth_state(session, employee)
    monkeypatch.setattr(
        "app.api.facebook.exchange_code_for_token",
        lambda code: pytest.fail("Graph exchange must not occur"),
    )
    assert (
        client.get(f"/api/v1/facebook/auth/callback?state={state}&code=unused").status_code == 403
    )


def test_health_and_provider_ingress_remain_public(
    authorization_context: tuple[TestClient, Session],
) -> None:
    client, _ = authorization_context
    assert client.get("/api/v1/system/health").status_code == 200
    assert client.get("/api/v1/facebook/webhook").status_code != 401
    assert client.post("/api/v1/facebook/webhook", content=b"{}").status_code != 401
