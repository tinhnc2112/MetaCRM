"""Tests for TASK-0010: Facebook Messenger Webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.customer_core import Customer, CustomerIdentity
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import FacebookApiError
from app.services.facebook.messenger import (
    FacebookWebhookSignatureError,
    RawMessageEvent,
    parse_webhook_payload,
    process_webhook_events,
    upsert_conversation,
    upsert_message,
    verify_webhook_signature,
)
from app.utils.jwt import create_access_token
from app.websocket.manager import ConnectionManager
from fastapi import status
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_TOKEN_KEY = "test-facebook-token-encryption-key"
TEST_APP_SECRET = "test-app-secret"
TEST_VERIFY_TOKEN = "test-verify-token"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    monkeypatch.setenv("FACEBOOK_APP_SECRET", TEST_APP_SECRET)
    monkeypatch.setenv("FACEBOOK_WEBHOOK_VERIFY_TOKEN", TEST_VERIFY_TOKEN)
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    db = local_session()

    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="hashed",
        full_name="Alice",
    )
    db.add(user)
    db.commit()

    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id="fb-alice",
        access_token_encrypted=cipher.encrypt("user-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(account)
    db.commit()

    page = FacebookPage(
        facebook_account_id=account.id,
        page_id="page-111",
        name="Alice Page",
        is_active=True,
    )
    db.add(page)
    db.commit()
    db.refresh(page)

    try:
        yield db
    finally:
        db.close()
        engine.dispose()
        get_settings.cache_clear()


@pytest.fixture()
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr("app.startup.lifecycle.init_db", lambda: None)

    def override_db() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_db

    # Inject a real ConnectionManager (broadcast is a no-op with no subscribers)
    mock_manager = ConnectionManager()
    app.state.manager = mock_manager

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _make_signature(body: bytes, secret: str = TEST_APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _websocket_url(*, page_id: str | None = None) -> str:
    params: list[str] = []
    if page_id is not None:
        params.append(f"page_id={page_id}")
    query = f"?{'&'.join(params)}" if params else ""
    return f"/api/v1/ws{query}"


def _access_token(session: Session, username: str = "alice") -> str:
    user = session.query(User).filter(User.username == username).one()
    return create_access_token(str(user.uuid))


def _add_user_page(session: Session, *, username: str, page_id: str) -> tuple[User, FacebookPage]:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash="hashed",
        full_name=username.title(),
    )
    session.add(user)
    session.flush()
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id=f"fb-{username}",
        access_token_encrypted=cipher.encrypt(f"{username}-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(account)
    session.flush()
    page = FacebookPage(
        facebook_account_id=account.id,
        page_id=page_id,
        name=f"{username.title()} Page",
        is_active=True,
    )
    session.add(page)
    session.commit()
    return user, page


def _websocket_protocols(access_token: str) -> list[str]:
    return ["metacrm", f"bearer.{access_token}"]


def _assert_websocket_rejected(
    client: TestClient,
    url: str,
    *,
    access_token: str | None = None,
) -> None:
    protocols = _websocket_protocols(access_token) if access_token is not None else None
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(url, subprotocols=protocols) as websocket:
            websocket.receive_json()
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def _message_payload(
    page_id: str = "page-111",
    psid: str = "user-psid-1",
    mid: str = "m_abc123",
    text: str = "Hello",
    timestamp: int = 1_700_000_000_000,
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": timestamp,
                "messaging": [
                    {
                        "sender": {"id": psid},
                        "recipient": {"id": page_id},
                        "timestamp": timestamp,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


def _postback_payload(
    page_id: str = "page-111",
    psid: str = "user-psid-1",
    timestamp: int = 1_700_000_001_000,
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "messaging": [
                    {
                        "sender": {"id": psid},
                        "recipient": {"id": page_id},
                        "timestamp": timestamp,
                        "postback": {"title": "Get Started", "payload": "GET_STARTED"},
                    }
                ],
            }
        ],
    }


def _read_payload(
    page_id: str = "page-111",
    psid: str = "user-psid-1",
    watermark: int = 1_700_000_000_000,
    timestamp: int = 1_700_000_002_000,
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "messaging": [
                    {
                        "sender": {"id": psid},
                        "recipient": {"id": page_id},
                        "timestamp": timestamp,
                        "read": {"watermark": watermark},
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Unit tests — verify_webhook_signature
# ---------------------------------------------------------------------------


def test_valid_signature_passes() -> None:
    body = b'{"object":"page"}'
    sig = _make_signature(body)
    verify_webhook_signature(body, sig, TEST_APP_SECRET)  # must not raise


def test_missing_signature_raises() -> None:
    with pytest.raises(FacebookWebhookSignatureError, match="Missing or malformed"):
        verify_webhook_signature(b"body", None, TEST_APP_SECRET)


def test_malformed_signature_prefix_raises() -> None:
    with pytest.raises(FacebookWebhookSignatureError, match="Missing or malformed"):
        verify_webhook_signature(b"body", "md5=deadbeef", TEST_APP_SECRET)


def test_wrong_signature_raises() -> None:
    body = b'{"object":"page"}'
    with pytest.raises(FacebookWebhookSignatureError, match="does not match"):
        verify_webhook_signature(body, "sha256=deadbeefdeadbeef", TEST_APP_SECRET)


# ---------------------------------------------------------------------------
# Unit tests — parse_webhook_payload
# ---------------------------------------------------------------------------


def test_parse_message_event() -> None:
    events = parse_webhook_payload(_message_payload())
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "message"
    assert e.mid == "m_abc123"
    assert e.text == "Hello"
    assert e.psid == "user-psid-1"
    assert e.page_id == "page-111"
    assert not e.is_from_page


def test_parse_postback_event() -> None:
    events = parse_webhook_payload(_postback_payload())
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "postback"
    assert e.postback_payload == "GET_STARTED"
    assert e.text == "Get Started"
    assert not e.is_from_page


def test_parse_read_event() -> None:
    events = parse_webhook_payload(_read_payload())
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "read"
    assert e.mid is not None  # synthetic mid
    assert e.text is None


def test_parse_non_page_object_returns_empty() -> None:
    payload = {"object": "instagram", "entry": []}
    events = parse_webhook_payload(payload)
    assert events == []


def test_parse_multiple_entries() -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-111",
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "recipient": {"id": "page-111"},
                        "timestamp": 1_700_000_000_000,
                        "message": {"mid": "m_1", "text": "hi"},
                    }
                ],
            },
            {
                "id": "page-111",
                "messaging": [
                    {
                        "sender": {"id": "psid-2"},
                        "recipient": {"id": "page-111"},
                        "timestamp": 1_700_000_001_000,
                        "message": {"mid": "m_2", "text": "hey"},
                    }
                ],
            },
        ],
    }
    events = parse_webhook_payload(payload)
    assert len(events) == 2
    assert {e.mid for e in events} == {"m_1", "m_2"}


def test_parse_skips_message_without_mid() -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-111",
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "recipient": {"id": "page-111"},
                        "timestamp": 1_700_000_000_000,
                        "message": {"text": "no mid here"},  # no mid
                    }
                ],
            }
        ],
    }
    assert parse_webhook_payload(payload) == []


# ---------------------------------------------------------------------------
# Unit tests — persistence helpers (upsert_conversation / upsert_message)
# ---------------------------------------------------------------------------


def test_upsert_conversation_creates_new(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    conv = upsert_conversation(session, page, "psid-new", None)
    session.commit()
    assert conv.id is not None
    assert conv.psid == "psid-new"
    assert conv.facebook_page_id == page.id


def test_upsert_conversation_is_idempotent(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    conv1 = upsert_conversation(session, page, "psid-dup", None)
    session.commit()
    conv2 = upsert_conversation(session, page, "psid-dup", None)
    session.commit()
    assert conv1.id == conv2.id


def test_upsert_conversation_links_legacy_conversation_without_customer(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    legacy = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid="psid-legacy",
    )
    session.add(legacy)
    session.commit()
    session.refresh(legacy)
    assert legacy.customer_id is None

    resolved = upsert_conversation(session, page, "psid-legacy", datetime(2026, 8, 17, tzinfo=UTC))
    session.commit()
    session.refresh(resolved)

    assert resolved.id == legacy.id
    assert resolved.customer_id is not None
    assert session.query(Customer).count() == 1
    assert session.query(CustomerIdentity).count() == 1

    resolved_again = upsert_conversation(session, page, "psid-legacy", datetime(2026, 8, 17, 1, tzinfo=UTC))
    session.commit()
    session.refresh(resolved_again)

    assert resolved_again.id == legacy.id
    assert session.query(Customer).count() == 1
    assert session.query(CustomerIdentity).count() == 1


def test_upsert_conversation_restores_missing_identity_for_linked_customer(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    customer = Customer(name="Linked Customer")
    session.add(customer)
    session.commit()
    session.refresh(customer)

    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid="psid-linked",
        customer_id=customer.id,
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)

    assert session.query(CustomerIdentity).count() == 0

    resolved = upsert_conversation(session, page, "psid-linked", datetime(2026, 8, 17, tzinfo=UTC))
    session.commit()
    session.refresh(resolved)

    assert resolved.id == conversation.id
    assert resolved.customer_id == customer.id
    identity = session.query(CustomerIdentity).filter(CustomerIdentity.external_id == "psid-linked").one()
    assert identity.customer_id == customer.id
    assert session.query(Customer).count() == 1


def test_upsert_conversation_repoints_merged_customer_to_primary(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    primary = Customer(name="Primary")
    secondary = Customer(name="Secondary", merged_into=primary)
    session.add_all([primary, secondary])
    session.commit()
    session.refresh(primary)
    session.refresh(secondary)

    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid="psid-merged-secondary",
        customer_id=secondary.id,
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)

    resolved = upsert_conversation(session, page, "psid-merged-secondary", datetime(2026, 8, 17, tzinfo=UTC))
    session.commit()
    session.refresh(resolved)

    assert resolved.id == conversation.id
    assert resolved.customer_id == primary.id
    identity = session.query(CustomerIdentity).filter(CustomerIdentity.external_id == "psid-merged-secondary").one()
    assert identity.customer_id == primary.id
    assert session.query(Customer).count() == 2


def test_upsert_conversation_updates_last_message_at(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    conv = upsert_conversation(session, page, "psid-ts", t1)
    session.commit()
    assert conv.last_message_at == t1
    # second call with later timestamp should update
    upsert_conversation(session, page, "psid-ts", t2)
    session.commit()
    assert conv.last_message_at == t2


def test_upsert_message_creates_new(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    conv = upsert_conversation(session, page, "psid-msg", None)
    session.flush()
    event = RawMessageEvent(
        page_id="page-111",
        psid="psid-msg",
        mid="m_unique_1",
        event_type="message",
        is_from_page=False,
        text="Hello",
        postback_payload=None,
        fb_timestamp_ms=1_700_000_000_000,
    )
    msg, created = upsert_message(session, conv, event)
    session.commit()
    assert created is True
    assert msg.mid == "m_unique_1"
    assert msg.text == "Hello"


def test_upsert_message_is_idempotent(session: Session) -> None:
    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    conv = upsert_conversation(session, page, "psid-idem", None)
    session.flush()
    event = RawMessageEvent(
        page_id="page-111",
        psid="psid-idem",
        mid="m_dup_1",
        event_type="message",
        is_from_page=False,
        text="First",
        postback_payload=None,
        fb_timestamp_ms=None,
    )
    msg1, created1 = upsert_message(session, conv, event)
    session.commit()
    msg2, created2 = upsert_message(session, conv, event)
    session.commit()
    assert created1 is True
    assert created2 is False
    assert msg1.id == msg2.id


def test_process_webhook_events_skips_unknown_page(session: Session) -> None:
    events = [
        RawMessageEvent(
            page_id="page-unknown-999",
            psid="psid-x",
            mid="m_x",
            event_type="message",
            is_from_page=False,
            text="hi",
            postback_payload=None,
            fb_timestamp_ms=None,
        )
    ]
    results = process_webhook_events(session, events)
    assert results == []
    # No conversation should have been created
    assert session.query(Conversation).count() == 0


def test_profile_lookup_persists_identity_on_first_message(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(self, path: str, params: dict[str, object] | None = None, access_token: str | None = None):
        return {
            "name": "Customer One",
            "picture": {"data": {"url": "https://example.com/customer.png"}},
        }

    monkeypatch.setattr("app.services.facebook.messenger.FacebookGraphClient.get", fake_get)

    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    events = parse_webhook_payload(_message_payload(psid="psid-profile-1"))
    results = process_webhook_events(session, events)

    assert len(results) == 1
    conversation = session.query(Conversation).one()
    assert conversation.customer_name == "Customer One"
    assert conversation.customer_avatar_url == "https://example.com/customer.png"


def test_profile_lookup_failure_does_not_block_message_persistence(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(self, path: str, params: dict[str, object] | None = None, access_token: str | None = None):
        raise FacebookApiError("profile lookup failed")

    monkeypatch.setattr("app.services.facebook.messenger.FacebookGraphClient.get", fake_get)

    events = parse_webhook_payload(_message_payload(psid="psid-profile-2"))
    results = process_webhook_events(session, events)

    assert len(results) == 1
    assert session.query(Conversation).count() == 1
    assert session.query(Message).count() == 1


def test_existing_identity_is_not_refetched(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, object] | None, str | None]] = []

    def fake_get(self, path: str, params: dict[str, object] | None = None, access_token: str | None = None):
        calls.append((path, params, access_token))
        return {
            "name": "Customer Two",
            "picture": {"data": {"url": "https://example.com/customer-2.png"}},
        }

    monkeypatch.setattr("app.services.facebook.messenger.FacebookGraphClient.get", fake_get)

    page = session.query(FacebookPage).filter(FacebookPage.page_id == "page-111").one()
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid="psid-profile-3",
        customer_name="Already Known",
        customer_avatar_url="https://example.com/already-known.png",
    )
    session.add(conversation)
    session.commit()

    events = parse_webhook_payload(_message_payload(psid="psid-profile-3", mid="mid-profile-3"))
    process_webhook_events(session, events)

    assert calls == []


# ---------------------------------------------------------------------------
# Integration tests — HTTP endpoint
# ---------------------------------------------------------------------------


class TestWebhookVerify:
    def test_valid_challenge_returns_challenge_value(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/facebook/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": TEST_VERIFY_TOKEN,
                "hub.challenge": "9876543210",
            },
        )
        assert response.status_code == 200
        assert response.json() == 9876543210

    def test_wrong_verify_token_returns_403(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/facebook/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "123",
            },
        )
        assert response.status_code == 403

    def test_wrong_mode_returns_400(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/facebook/webhook",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": TEST_VERIFY_TOKEN,
                "hub.challenge": "123",
            },
        )
        assert response.status_code == 400

    def test_missing_challenge_returns_400(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/facebook/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": TEST_VERIFY_TOKEN,
            },
        )
        assert response.status_code == 400


class TestWebhookReceive:
    def _post(
        self, client: TestClient, payload: dict, secret: str = TEST_APP_SECRET
    ):
        body = json.dumps(payload).encode()
        return client.post(
            "/api/v1/facebook/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _make_signature(body, secret),
            },
        )

    def test_valid_message_event_persisted(
        self, client: TestClient, session: Session
    ) -> None:
        response = self._post(client, _message_payload())
        assert response.status_code == 200
        assert response.json()["events_processed"] == 1
        assert session.query(Conversation).count() == 1
        assert session.query(Message).count() == 1
        msg = session.query(Message).one()
        assert msg.mid == "m_abc123"
        assert msg.text == "Hello"
        assert msg.event_type == "message"

    def test_duplicate_event_is_idempotent(
        self, client: TestClient, session: Session
    ) -> None:
        payload = _message_payload()
        self._post(client, payload)
        response = self._post(client, payload)
        assert response.status_code == 200
        # Second call: event_processed=1 because upsert returns existing, was_created=False
        assert session.query(Message).count() == 1  # still only one message

    def test_invalid_signature_returns_403(self, client: TestClient) -> None:
        body = json.dumps(_message_payload()).encode()
        response = client.post(
            "/api/v1/facebook/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=deadbeefdeadbeef",
            },
        )
        assert response.status_code == 403

    def test_missing_signature_returns_403(self, client: TestClient) -> None:
        body = json.dumps(_message_payload()).encode()
        response = client.post(
            "/api/v1/facebook/webhook",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 403

    def test_non_page_object_returns_200_no_persist(
        self, client: TestClient, session: Session
    ) -> None:
        payload = {"object": "instagram", "entry": []}
        response = self._post(client, payload)
        assert response.status_code == 200
        assert response.json()["events_processed"] == 0
        assert session.query(Conversation).count() == 0

    def test_postback_event_persisted(
        self, client: TestClient, session: Session
    ) -> None:
        response = self._post(client, _postback_payload())
        assert response.status_code == 200
        msg = session.query(Message).one()
        assert msg.event_type == "postback"
        assert msg.postback_payload == "GET_STARTED"

    def test_read_event_persisted(
        self, client: TestClient, session: Session
    ) -> None:
        response = self._post(client, _read_payload())
        assert response.status_code == 200
        msg = session.query(Message).one()
        assert msg.event_type == "read"

    def test_unknown_page_id_returns_200_no_persist(
        self, client: TestClient, session: Session
    ) -> None:
        payload = _message_payload(page_id="page-unknown-999")
        response = self._post(client, payload)
        assert response.status_code == 200
        assert session.query(Conversation).count() == 0

    def test_broadcast_called_for_new_message(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ConnectionManager.broadcast is awaited for newly created messages."""
        mock_manager = MagicMock(spec=ConnectionManager)
        mock_manager.broadcast = AsyncMock()
        app.state.manager = mock_manager

        self._post(client, _message_payload())

        mock_manager.broadcast.assert_awaited_once()
        call_kwargs = mock_manager.broadcast.call_args
        channel = call_kwargs.kwargs.get("channel") or call_kwargs.args[1]
        assert channel == "page:page-111"
        broadcasted = json.loads(call_kwargs.args[0])
        assert broadcasted["type"] == "new_message"
        assert set(broadcasted) == {"type", "conversation_id"}

    def test_broadcast_not_called_for_duplicate(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Duplicate mid must NOT trigger a second broadcast."""
        payload = _message_payload()
        # First call — real manager
        self._post(client, payload)

        mock_manager = MagicMock(spec=ConnectionManager)
        mock_manager.broadcast = AsyncMock()
        app.state.manager = mock_manager

        # Second call — duplicate
        self._post(client, payload)
        mock_manager.broadcast.assert_not_awaited()


# ---------------------------------------------------------------------------
# Authenticated WebSocket security regression tests
# ---------------------------------------------------------------------------


class TestAuthenticatedWebSocket:
    def test_unauthenticated_websocket_is_rejected(self, client: TestClient) -> None:
        _assert_websocket_rejected(client, _websocket_url(page_id="page-111"))

    def test_malformed_token_is_rejected(self, client: TestClient) -> None:
        _assert_websocket_rejected(
            client,
            _websocket_url(page_id="page-111"),
            access_token="not-a-jwt",
        )

    def test_expired_token_is_rejected(self, client: TestClient, session: Session) -> None:
        settings = get_settings()
        original_expiry = settings.access_token_expire_minutes
        try:
            settings.access_token_expire_minutes = -1
            expired_token = _access_token(session)
        finally:
            settings.access_token_expire_minutes = original_expiry

        _assert_websocket_rejected(
            client,
            _websocket_url(page_id="page-111"),
            access_token=expired_token,
        )

    def test_owner_can_connect_and_ping(self, client: TestClient, session: Session) -> None:
        token = _access_token(session)
        url = _websocket_url(page_id="page-111")
        with client.websocket_connect(url, subprotocols=_websocket_protocols(token)) as websocket:
            assert websocket.receive_json() == {"type": "connection", "status": "connected"}
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}

    def test_user_cannot_connect_to_foreign_page(
        self, client: TestClient, session: Session
    ) -> None:
        _add_user_page(session, username="bob", page_id="page-bob")
        _assert_websocket_rejected(
            client,
            _websocket_url(page_id="page-bob"),
            access_token=_access_token(session),
        )

    def test_unknown_page_is_rejected(self, client: TestClient, session: Session) -> None:
        _assert_websocket_rejected(
            client,
            _websocket_url(page_id="page-unknown"),
            access_token=_access_token(session),
        )

    def test_raw_channel_contract_is_rejected(self, client: TestClient, session: Session) -> None:
        token = _access_token(session)
        _assert_websocket_rejected(
            client,
            "/api/v1/ws?channel=page:page-111",
            access_token=token,
        )

    def test_access_token_in_query_string_is_rejected(
        self, client: TestClient, session: Session
    ) -> None:
        token = _access_token(session)
        _assert_websocket_rejected(
            client,
            f"/api/v1/ws?page_id=page-111&access_token={token}",
        )

    def test_inactive_user_is_rejected(self, client: TestClient, session: Session) -> None:
        user = session.query(User).filter(User.username == "alice").one()
        token = create_access_token(str(user.uuid))
        user.is_active = False
        session.commit()
        _assert_websocket_rejected(
            client,
            _websocket_url(page_id="page-111"),
            access_token=token,
        )

    def test_owner_receives_minimal_event_for_own_page(
        self, client: TestClient, session: Session
    ) -> None:
        token = _access_token(session)
        url = _websocket_url(page_id="page-111")
        with client.websocket_connect(url, subprotocols=_websocket_protocols(token)) as websocket:
            assert websocket.receive_json()["status"] == "connected"
            payload = _message_payload(text="sensitive message", psid="sensitive-psid")
            body = json.dumps(payload).encode()
            response = client.post(
                "/api/v1/facebook/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _make_signature(body),
                },
            )
            assert response.status_code == 200
            event = websocket.receive_json()
            assert event["type"] == "new_message"
            assert event["conversation_id"]
            assert set(event) == {"type", "conversation_id"}
            assert "psid" not in event
            assert "text" not in event

    def test_page_a_socket_does_not_receive_page_b_event(
        self, client: TestClient, session: Session
    ) -> None:
        _add_user_page(session, username="bob", page_id="page-bob")
        token = _access_token(session)
        url = _websocket_url(page_id="page-111")
        with client.websocket_connect(url, subprotocols=_websocket_protocols(token)) as websocket:
            assert websocket.receive_json()["status"] == "connected"
            payload = _message_payload(page_id="page-bob", mid="m_page_b")
            body = json.dumps(payload).encode()
            response = client.post(
                "/api/v1/facebook/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _make_signature(body),
                },
            )
            assert response.status_code == 200
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}
