from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.facebook import FacebookAccount, FacebookPage
from app.services.facebook.auth import (
    FACEBOOK_AUTH_SCOPES,
    create_oauth_state,
    generate_authorization_url,
    validate_oauth_state,
)
from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import FacebookApiError, FacebookOAuthStateError
from app.services.facebook.pages import FacebookPageData, sync_facebook_pages
from app.services.facebook.subscriptions import (
    subscribe_active_pages_to_messenger_webhooks,
    subscribe_page_to_messenger_webhooks,
)
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from fastapi.testclient import TestClient
from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    monkeypatch.setenv("FACEBOOK_APP_ID", "test-app-id")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("FACEBOOK_WEBHOOK_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setenv(
        "FACEBOOK_WEBHOOK_CALLBACK_URL",
        "https://example.trycloudflare.com/api/v1/facebook/webhook",
    )
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    database_session = local_session()
    database_session.add_all(
        [
            User(
                username="alice",
                email="alice@example.com",
                password_hash=hash_password("correct-password"),
                full_name="Alice Example",
            ),
            User(
                username="bob",
                email="bob@example.com",
                password_hash=hash_password("correct-password"),
                full_name="Bob Example",
            ),
        ]
    )
    database_session.commit()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()
        get_settings.cache_clear()


@pytest.fixture()
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr("app.startup.lifecycle.init_db", lambda: None)

    def override_db() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def create_account_with_pages(session: Session, user: User, page_id: str = "page-1") -> FacebookPage:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id=f"fb-{user.username}",
        access_token_encrypted=cipher.encrypt("user-access-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(account)
    session.commit()
    page = FacebookPage(
        facebook_account_id=account.id,
        page_id=page_id,
        name=f"{user.username} Page",
        username=f"{user.username}-page",
        picture_url="https://example.com/page.png",
        access_token_encrypted=cipher.encrypt("page-access-token"),
        is_active=True,
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    return page


def test_oauth_state_generation_and_single_use_validation(session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    state = create_oauth_state(session, user)

    assert state
    assert validate_oauth_state(session, state).id == user.id

    with pytest.raises(FacebookOAuthStateError):
        validate_oauth_state(session, state)


def test_facebook_oauth_url_requests_exact_messenger_scopes(session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()

    url = generate_authorization_url(session, user)
    query = parse_qs(urlsplit(url).query)

    assert query["scope"] == [",".join(FACEBOOK_AUTH_SCOPES)]
    assert FACEBOOK_AUTH_SCOPES == (
        "public_profile",
        "pages_show_list",
        "pages_read_engagement",
        "pages_manage_metadata",
        "pages_messaging",
    )
    assert "business_management" not in FACEBOOK_AUTH_SCOPES


def test_token_encryption_round_trip() -> None:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    encrypted = cipher.encrypt("facebook-access-token")

    assert encrypted != "facebook-access-token"
    assert cipher.decrypt(encrypted) == "facebook-access-token"


def test_facebook_account_creation_and_page_sync(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id="fb-user-1",
        access_token_encrypted=cipher.encrypt("user-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(account)
    session.commit()

    monkeypatch.setattr(
        "app.services.facebook.pages.retrieve_available_pages",
        lambda access_token, client=None: [
            FacebookPageData(
                page_id="page-1",
                name="Page One",
                username="pageone",
                picture_url="https://example.com/p.png",
                access_token="page-token",
            )
        ],
    )
    subscribed_page_ids: list[str] = []
    monkeypatch.setattr(
        "app.services.facebook.pages.subscribe_active_pages_to_messenger_webhooks",
        lambda session, pages, cipher=None: subscribed_page_ids.extend(
            page.page_id for page in pages
        ),
    )

    pages = sync_facebook_pages(session, account, cipher=cipher)

    assert len(pages) == 1
    assert pages[0].page_id == "page-1"
    assert pages[0].access_token_encrypted != "page-token"
    assert cipher.decrypt(pages[0].access_token_encrypted or "") == "page-token"
    assert subscribed_page_ids == ["page-1"]


def test_page_listing_does_not_expose_tokens(client: TestClient, session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)

    response = client.get("/api/v1/facebook/pages", headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["page_id"] == "page-1"
    assert "access_token" not in str(body)
    assert "page-access-token" not in str(body)


def test_page_selection_and_current_page(client: TestClient, session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)

    selected = client.post("/api/v1/facebook/pages/page-1/select", headers=auth_headers(user))
    current = client.get("/api/v1/facebook/pages/current", headers=auth_headers(user))

    assert selected.status_code == 200
    assert selected.json()["item"]["page_id"] == "page-1"
    assert current.status_code == 200
    assert current.json()["item"]["page_id"] == "page-1"


class StubSubscriptionClient:
    def __init__(self, responses: list[dict[str, bool] | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post(self, path: str, data: dict[str, str]) -> dict[str, bool]:
        self.calls.append((path, data))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class StubDebugGraphClient:
    def __init__(
        self,
        get_response: dict | None = None,
        get_responses: dict[str, dict | list[dict]] | None = None,
    ) -> None:
        self.get_response = get_response or {"data": []}
        self.get_responses = get_responses or {}
        self.get_calls: list[tuple[str, dict | None, str | None]] = []
        self.post_calls: list[tuple[str, dict]] = []

    def get(
        self,
        path: str,
        params: dict | None = None,
        access_token: str | None = None,
    ) -> dict:
        self.get_calls.append((path, params, access_token))
        response = self.get_responses.get(path, self.get_response)
        if isinstance(response, list):
            return response.pop(0)
        return response

    def post(self, path: str, data: dict) -> dict:
        self.post_calls.append((path, data))
        return {"success": True}


def test_debug_subscribed_apps_returns_raw_graph_response(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph_response = {
        "data": [
            {
                "id": "test-app-id",
                "name": "MetaCRM",
                "subscribed_fields": ["messages", "messaging_postbacks"],
            }
        ]
    }
    graph = StubDebugGraphClient(graph_response)
    monkeypatch.setattr("app.api.facebook.FacebookGraphClient", lambda: graph)

    response = client.get(
        "/api/v1/facebook/debug/subscribed-apps/page-1",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json() == {
        "page_id": "page-1",
        "app_id": "test-app-id",
        "subscribed_fields": ["messages", "messaging_postbacks"],
        "graph_response": graph_response,
    }
    assert graph.get_calls == [
        ("/page-1/subscribed_apps", None, "page-access-token")
    ]


def test_debug_page_token_returns_only_token_metadata(
    client: TestClient,
    session: Session,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    page = create_account_with_pages(session, user)
    token = "page-access-token-that-is-longer-than-thirty-characters"
    page.access_token_encrypted = TokenCipher(TEST_TOKEN_KEY).encrypt(token)
    page.token_expires_at = datetime.now(UTC) + timedelta(days=10)
    session.commit()

    response = client.get(
        "/api/v1/facebook/debug/page-token/page-1",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["token_available"] is True
    assert response.json()["expires_at"] is not None
    assert token not in response.text
    assert token[:30] not in response.text


def test_debug_page_token_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/facebook/debug/page-token/page-1")
    assert response.status_code == 401


def test_debug_graph_response_redacts_nested_credentials() -> None:
    from app.api.facebook import safe_graph_diagnostics

    secret = "credential-marker-example"
    data = {"data": [{"id": "app-1", "access_token": secret,
                       "message": f"provider error: {secret}",
                       "nested": {"client_secret": secret, "cookie": secret}}]}
    rendered = str(safe_graph_diagnostics(data))
    assert secret not in rendered
    assert "app-1" in rendered


def test_graph_diagnostic_allowlist_preserves_subscription_evidence() -> None:
    from app.api.facebook import safe_graph_diagnostics

    secret = "credential-fragment-marker"
    response = {
        "data": [{
            "id": "app-1", "name": "MetaCRM", "object": "page",
            "callback_url": "https://example.com/webhook",
            "fields": [{"name": "messages", "version": "v26.0"}],
            "subscribed_fields": ["messages"], "active": True,
            "access_token": secret, "message": secret, "error": {"detail": secret},
        }],
        "success": True,
    }
    safe = safe_graph_diagnostics(response)
    item = safe["data"][0]
    assert item["id"] == "app-1"
    assert item["name"] == "MetaCRM"
    assert item["object"] == "page"
    assert item["callback_url"] == "https://example.com/webhook"
    assert item["fields"] == [{"name": "messages", "version": "v26.0"}]
    assert item["subscribed_fields"] == ["messages"]
    assert item["active"] is True
    assert safe["success"] is True
    assert item["access_token"] == item["message"] == item["error"] == "<redacted>"
    assert secret not in str(safe)


def test_provider_error_never_returns_or_logs_token_fragment() -> None:
    secret = "credential-fragment-marker-98765"
    logged: list[str] = []
    sink = logger.add(lambda message: logged.append(str(message)))
    try:
        error = FacebookGraphClient()._api_error(
            '{"error":{"code":190,"message":"token ' + secret + '"}}', 401
        )
    finally:
        logger.remove(sink)
    assert secret not in str(error) + "".join(logged)
    assert "token was rejected" in str(error)


def test_debug_token_scopes_returns_user_token_permissions(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph = StubDebugGraphClient(
        get_responses={
            "/debug_token": {
                "data": {
                    "app_id": "test-app-id",
                    "type": "USER",
                    "is_valid": True,
                    "user_id": "fb-alice",
                    "expires_at": 1_800_000_000,
                    "scopes": ["pages_show_list", "pages_messaging"],
                }
            },
            "/me/permissions": {
                "data": [
                    {"permission": "pages_show_list", "status": "granted"},
                    {"permission": "pages_messaging", "status": "granted"},
                    {"permission": "business_management", "status": "declined"},
                ]
            },
        }
    )
    monkeypatch.setattr("app.api.facebook.FacebookGraphClient", lambda: graph)

    response = client.get(
        "/api/v1/facebook/debug/token-scopes",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "token_type": "USER",
        "app_id": "test-app-id",
        "user_id": "fb-alice",
        "granted_scopes": ["pages_messaging", "pages_show_list"],
        "declined_scopes": ["business_management"],
        "expires_at": 1_800_000_000,
    }
    assert "user-access-token" not in response.text
    assert graph.get_calls[0] == (
        "/debug_token",
        {"input_token": "user-access-token"},
        "test-app-id|test-app-secret",
    )


def test_debug_page_permissions_returns_page_tasks_and_capabilities(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph = StubDebugGraphClient(
        get_responses={
            "/page-1": {
                "id": "page-1",
                "name": "Alice Page",
                "category": "Business",
                "permissions": ["MESSAGING"],
            },
            "/me/accounts": {
                "data": [
                    {
                        "id": "page-1",
                        "name": "Alice Page",
                        "category": "Business",
                        "tasks": ["MESSAGING", "MODERATE"],
                    }
                ]
            },
        }
    )
    monkeypatch.setattr("app.api.facebook.FacebookGraphClient", lambda: graph)

    response = client.get(
        "/api/v1/facebook/debug/page-permissions/page-1",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json() == {
        "page_id": "page-1",
        "page_name": "Alice Page",
        "tasks": ["MESSAGING", "MODERATE"],
        "category": "Business",
        "permissions": ["MESSAGING"],
    }


def test_debug_app_mode_reports_app_and_messenger_webhook_configuration(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    graph = StubDebugGraphClient(
        get_responses={
            "/test-app-id": {"id": "test-app-id", "name": "MetaCRM"},
            "/test-app-id/subscriptions": {
                "data": [
                    {
                        "object": "page",
                        "callback_url": "https://example.com/api/v1/facebook/webhook",
                        "fields": [
                            {"name": "messages", "version": "v25.0"},
                            {"name": "messaging_postbacks", "version": "v25.0"},
                        ],
                    }
                ]
            },
        }
    )
    monkeypatch.setattr("app.api.facebook.FacebookGraphClient", lambda: graph)

    response = client.get(
        "/api/v1/facebook/debug/app-mode",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json() == {
        "app_id": "test-app-id",
        "app_name": "MetaCRM",
        "app_mode": "unknown",
        "has_messenger_product": True,
    }


def test_debug_page_info_uses_supported_page_fields_and_accounts_tasks(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph = StubDebugGraphClient(
        get_responses={
            "/page-1": {
                "id": "page-1",
                "name": "Alice Page",
                "category": "Business",
            },
            "/me/accounts": {
                "data": [
                    {"id": "page-1", "name": "Alice Page", "tasks": ["MESSAGING"]}
                ]
            },
        }
    )
    monkeypatch.setattr(
        "app.api.facebook.FacebookGraphClient",
        lambda api_version=None: graph,
    )

    response = client.get(
        "/api/v1/facebook/debug/page-info/page-1",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["tasks"] == ["MESSAGING"]
    assert graph.get_calls == [
        ("/page-1", {"fields": "id,name,category"}, "page-access-token"),
        ("/me/accounts", {"fields": "id,name,tasks"}, "user-access-token"),
    ]


def test_debug_app_info_returns_unknown_for_unexposed_dashboard_states(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    graph = StubDebugGraphClient(
        get_responses={
            "/test-app-id": {"id": "test-app-id", "name": "MetaCRM"},
            "/test-app-id/subscriptions": {
                "data": [
                    {
                        "object": "page",
                        "callback_url": "https://example.trycloudflare.com/api/v1/facebook/webhook",
                        "fields": [{"name": "messages", "version": "v26.0"}],
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(
        "app.api.facebook.FacebookGraphClient",
        lambda api_version=None: graph,
    )

    response = client.get(
        "/api/v1/facebook/debug/app-info",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["app_id"] == "test-app-id"
    assert body["app_name"] == "MetaCRM"
    assert body["app_mode"] == "UNKNOWN"
    assert body["messenger_product_enabled"] == "UNKNOWN"
    assert body["webhook_product_enabled"] == "UNKNOWN"
    assert body["graph_evidence"]["page_messages_subscription_present"] is True
    assert body["graph_evidence"]["app_subscriptions"]["data"][0]["fields"] == [
        {"name": "messages", "version": "v26.0"}
    ]


def test_debug_webhook_subscriptions_confirms_matching_app_ids(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph = StubDebugGraphClient(
        get_responses={
            "/test-app-id": {"id": "test-app-id", "name": "MetaCRM"},
            "/test-app-id/subscriptions": {
                "data": [
                    {
                        "object": "page",
                        "callback_url": "https://example.trycloudflare.com/api/v1/facebook/webhook",
                        "fields": [{"name": "messages", "version": "v26.0"}],
                    }
                ]
            },
            "/page-1/subscribed_apps": {
                "data": [
                    {"id": "test-app-id", "subscribed_fields": ["messages"]}
                ]
            },
            "/debug_token": [
                {"data": {"type": "USER", "app_id": "test-app-id"}},
                {"data": {"type": "PAGE", "app_id": "test-app-id"}},
            ],
        }
    )
    monkeypatch.setattr(
        "app.api.facebook.FacebookGraphClient",
        lambda api_version=None: graph,
    )

    response = client.get(
        "/api/v1/facebook/debug/webhook-subscriptions",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subscribed_fields"] == ["messages"]
    assert body["page_subscriptions"]["data"][0]["subscribed_fields"] == ["messages"]
    assert body["app_subscriptions"]["data"][0]["fields"] == [
        {"name": "messages", "version": "v26.0"}
    ]
    assert body["callback_url"] == (
        "https://example.trycloudflare.com/api/v1/facebook/webhook"
    )
    assert body["app_id_consistency"]["status"] == "PASS"
    assert set(body["app_id_consistency"]["values"].values()) == {"test-app-id"}
    assert body["app_id_consistency"]["webhook_payload_app_id"] == "UNKNOWN"
    assert "user-access-token" not in response.text
    assert "page-access-token" not in response.text


def test_debug_webhook_subscriptions_reports_page_token_app_id_mismatch(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph = StubDebugGraphClient(
        get_responses={
            "/test-app-id": {"id": "test-app-id", "name": "MetaCRM"},
            "/test-app-id/subscriptions": {"data": []},
            "/page-1/subscribed_apps": {
                "data": [{"id": "test-app-id", "subscribed_fields": ["messages"]}]
            },
            "/debug_token": [
                {"data": {"type": "USER", "app_id": "test-app-id"}},
                {"data": {"type": "PAGE", "app_id": "different-app-id"}},
            ],
        }
    )
    monkeypatch.setattr(
        "app.api.facebook.FacebookGraphClient",
        lambda api_version=None: graph,
    )

    response = client.get(
        "/api/v1/facebook/debug/webhook-subscriptions",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["app_id_consistency"]["status"] == "FAIL"
    assert response.json()["app_id_consistency"]["failures"] == [
        "OAuth/runtime/token App IDs are not identical."
    ]


def test_messenger_diagnostics_collects_graph_v26_delivery_prerequisites(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph = StubDebugGraphClient(
        get_responses={
            "/test-app-id": {"id": "test-app-id", "name": "MetaCRM"},
            "/test-app-id/subscriptions": {
                "data": [
                    {
                        "object": "page",
                        "callback_url": "https://example.trycloudflare.com/api/v1/facebook/webhook",
                        "fields": [
                            {"name": "messages", "version": "v26.0"},
                            {"name": "messaging_postbacks", "version": "v26.0"},
                        ],
                    }
                ]
            },
            "/debug_token": [
                {
                    "data": {
                        "app_id": "test-app-id",
                        "type": "USER",
                        "is_valid": True,
                        "user_id": "fb-alice",
                        "expires_at": 1_800_000_000,
                    }
                },
                {
                    "data": {
                        "app_id": "test-app-id",
                        "type": "PAGE",
                        "is_valid": True,
                    }
                },
            ],
            "/me/permissions": {
                "data": [
                    {"permission": "pages_show_list", "status": "granted"},
                    {"permission": "pages_read_engagement", "status": "granted"},
                    {"permission": "pages_manage_metadata", "status": "granted"},
                    {"permission": "pages_messaging", "status": "granted"},
                ]
            },
            "/me/accounts": {
                "data": [
                    {"id": "page-1", "name": "Alice Page", "tasks": ["MESSAGING"]}
                ]
            },
            "/page-1": {"id": "page-1", "name": "Alice Page"},
            "/page-1/subscribed_apps": {
                "data": [
                    {
                        "id": "test-app-id",
                        "name": "MetaCRM",
                        "subscribed_fields": ["messages", "messaging_postbacks"],
                    }
                ]
            },
        }
    )
    created_versions: list[str | None] = []

    def graph_factory(api_version: str | None = None) -> StubDebugGraphClient:
        created_versions.append(api_version)
        return graph

    monkeypatch.setattr("app.api.facebook.FacebookGraphClient", graph_factory)

    response = client.get(
        "/api/v1/facebook/debug/messenger-diagnostics",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert created_versions == ["v26.0"]
    assert body["graph_api_version"] == "v26.0"
    assert body["app_id"] == "test-app-id"
    assert body["app_name"] == "MetaCRM"
    assert body["page_id"] == "page-1"
    assert body["page_name"] == "Alice Page"
    assert body["page_tasks"] == ["MESSAGING"]
    assert body["page_access_token_valid"] is True
    assert body["user_token_scopes"]["granted"] == [
        "pages_manage_metadata",
        "pages_messaging",
        "pages_read_engagement",
        "pages_show_list",
    ]
    assert body["messenger_product_status"] == "configured"
    assert body["webhook_callback"] == (
        "https://example.trycloudflare.com/api/v1/facebook/webhook"
    )
    assert body["graph_errors"] == []
    assert body["app_subscriptions"]["data"][0]["fields"] == [
        {"name": "messages", "version": "v26.0"},
        {"name": "messaging_postbacks", "version": "v26.0"},
    ]
    assert body["diagnosis"] == "WARNING"
    assert "user-access-token" not in response.text
    assert "page-access-token" not in response.text


def test_messenger_diagnostics_fails_when_pages_messaging_is_missing(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)
    graph = StubDebugGraphClient(
        get_responses={
            "/test-app-id": {"id": "test-app-id", "name": "MetaCRM"},
            "/test-app-id/subscriptions": {
                "data": [
                    {
                        "object": "page",
                        "callback_url": "https://example.trycloudflare.com/api/v1/facebook/webhook",
                        "fields": [{"name": "messages", "version": "v26.0"}],
                    }
                ]
            },
            "/debug_token": [
                {"data": {"type": "USER", "is_valid": True}},
                {"data": {"type": "PAGE", "is_valid": True}},
            ],
            "/me/permissions": {
                "data": [
                    {"permission": "pages_show_list", "status": "granted"},
                    {"permission": "pages_read_engagement", "status": "granted"},
                    {"permission": "pages_manage_metadata", "status": "granted"},
                ]
            },
            "/me/accounts": {
                "data": [{"id": "page-1", "tasks": ["MESSAGING"]}]
            },
            "/page-1": {"id": "page-1", "name": "Alice Page"},
            "/page-1/subscribed_apps": {
                "data": [
                    {"id": "test-app-id", "subscribed_fields": ["messages"]}
                ]
            },
        }
    )
    monkeypatch.setattr(
        "app.api.facebook.FacebookGraphClient",
        lambda api_version=None: graph,
    )

    response = client.get(
        "/api/v1/facebook/debug/messenger-diagnostics",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["diagnosis"] == "FAIL"
    assert any(
        "pages_messaging" in reason
        for reason in response.json()["diagnosis_reasons"]
    )


def test_debug_resubscribe_bypasses_db_status_without_writing_db(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    page = create_account_with_pages(session, user)
    page.webhook_subscription_status = "subscribed"
    page.webhook_subscription_attempt_count = 7
    session.commit()
    graph = StubDebugGraphClient()
    monkeypatch.setattr("app.api.facebook.FacebookGraphClient", lambda: graph)

    response = client.post(
        "/api/v1/facebook/debug/resubscribe/page-1",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["graph_response"] == {"success": True}
    assert graph.post_calls[0][0] == "/page-1/subscribed_apps"
    assert graph.post_calls[0][1]["access_token"] == "page-access-token"
    session.refresh(page)
    assert page.webhook_subscription_status == "subscribed"
    assert page.webhook_subscription_attempt_count == 7


def test_debug_webhook_health_reports_configuration_and_cloudflare(
    client: TestClient,
    session: Session,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()

    response = client.get(
        "/api/v1/facebook/debug/webhook-health",
        headers={**auth_headers(user), "CF-Ray": "test-ray"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "callback_url": "https://example.trycloudflare.com/api/v1/facebook/webhook",
        "verify_token_configured": True,
        "app_secret_configured": True,
        "cloudflare_reachable": True,
    }


def test_webhook_subscription_batch_only_calls_unsubscribed_active_pages(
    session: Session,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    subscribed_page = create_account_with_pages(session, user, page_id="subscribed-page")
    subscribed_page.webhook_subscription_status = "subscribed"
    subscribed_page.webhook_subscription_attempt_count = 2

    pending_page = FacebookPage(
        facebook_account_id=subscribed_page.facebook_account_id,
        page_id="pending-page",
        name="Pending Page",
        access_token_encrypted=TokenCipher(TEST_TOKEN_KEY).encrypt("pending-page-token"),
        is_active=True,
    )
    inactive_page = FacebookPage(
        facebook_account_id=subscribed_page.facebook_account_id,
        page_id="inactive-page",
        name="Inactive Page",
        access_token_encrypted=TokenCipher(TEST_TOKEN_KEY).encrypt("inactive-page-token"),
        is_active=False,
    )
    session.add_all([pending_page, inactive_page])
    session.commit()
    graph = StubSubscriptionClient([{"success": True}])

    subscribe_active_pages_to_messenger_webhooks(
        session,
        [subscribed_page, pending_page, inactive_page],
        client=graph,  # type: ignore[arg-type]
        cipher=TokenCipher(TEST_TOKEN_KEY),
        sleep=lambda _: None,
    )

    assert [call[0] for call in graph.calls] == ["/pending-page/subscribed_apps"]
    assert subscribed_page.webhook_subscription_attempt_count == 2
    assert pending_page.webhook_subscription_status == "subscribed"
    assert pending_page.webhook_subscription_attempt_count == 1
    assert inactive_page.webhook_subscription_status == "pending"
    assert inactive_page.webhook_subscription_attempt_count == 0


def test_webhook_subscription_is_idempotent(session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    page = create_account_with_pages(session, user)
    graph = StubSubscriptionClient([{"success": True}])

    first = subscribe_page_to_messenger_webhooks(
        session,
        page,
        client=graph,  # type: ignore[arg-type]
        cipher=TokenCipher(TEST_TOKEN_KEY),
        sleep=lambda _: None,
    )
    second = subscribe_page_to_messenger_webhooks(
        session,
        page,
        client=graph,  # type: ignore[arg-type]
        cipher=TokenCipher(TEST_TOKEN_KEY),
        sleep=lambda _: None,
    )

    assert first is True
    assert second is True
    assert len(graph.calls) == 1
    assert graph.calls[0][0] == "/page-1/subscribed_apps"
    assert graph.calls[0][1]["access_token"] == "page-access-token"
    assert page.webhook_subscription_status == "subscribed"
    assert page.webhook_subscription_attempt_count == 1
    assert page.webhook_subscribed_at is not None
    assert page.webhook_subscription_last_error is None


def test_webhook_subscription_retries_transient_errors(session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    page = create_account_with_pages(session, user)
    graph = StubSubscriptionClient(
        [
            FacebookApiError("temporary failure"),
            FacebookApiError("temporary failure"),
            {"success": True},
        ]
    )
    delays: list[float] = []

    subscribed = subscribe_page_to_messenger_webhooks(
        session,
        page,
        client=graph,  # type: ignore[arg-type]
        cipher=TokenCipher(TEST_TOKEN_KEY),
        sleep=delays.append,
    )

    assert subscribed is True
    assert len(graph.calls) == 3
    assert delays == [0.25, 0.5]
    assert page.webhook_subscription_status == "subscribed"
    assert page.webhook_subscription_attempt_count == 3


def test_webhook_subscription_records_failure_after_retries(session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    page = create_account_with_pages(session, user)
    graph = StubSubscriptionClient(
        [FacebookApiError("temporary failure") for _ in range(3)]
    )

    subscribed = subscribe_page_to_messenger_webhooks(
        session,
        page,
        client=graph,  # type: ignore[arg-type]
        cipher=TokenCipher(TEST_TOKEN_KEY),
        sleep=lambda _: None,
    )

    assert subscribed is False
    assert len(graph.calls) == 3
    assert page.webhook_subscription_status == "failed"
    assert page.webhook_subscription_attempt_count == 3
    assert page.webhook_subscription_last_error == "temporary failure"


def test_user_cannot_select_another_users_page(client: TestClient, session: Session) -> None:
    alice = session.query(User).filter(User.username == "alice").one()
    bob = session.query(User).filter(User.username == "bob").one()
    create_account_with_pages(session, bob, page_id="bob-page")

    response = client.post("/api/v1/facebook/pages/bob-page/select", headers=auth_headers(alice))

    assert response.status_code == 404
