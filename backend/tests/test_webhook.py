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
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.messenger import (
    FacebookWebhookSignatureError,
    RawMessageEvent,
    parse_webhook_payload,
    process_webhook_events,
    upsert_conversation,
    upsert_message,
    verify_webhook_signature,
)
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
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
        assert broadcasted["page_id"] == "page-111"

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
# WebSocket test — ConnectionManager integration
# ---------------------------------------------------------------------------


def test_websocket_uses_connection_manager(client: TestClient) -> None:
    """ws.py now connects/disconnects via app.state.manager."""
    with client.websocket_connect("/api/v1/ws?channel=page:page-111") as ws:
        data = ws.receive_json()
        assert data == {"type": "connection", "status": "connected"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
