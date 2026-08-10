"""Tests for TASK-0011 Part 1: Messenger CRM read API.

Covers:
- GET /api/v1/facebook/conversations  (list, filter, pagination, auth)
- GET /api/v1/facebook/conversations/{id}/messages  (list, pagination, auth, 404)
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from app.services.facebook.crypto import TokenCipher
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-0011"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()

    # Two users: alice and bob
    alice = User(
        username="alice_0011",
        email="alice_0011@example.com",
        password_hash=hash_password("pw"),
        full_name="Alice",
    )
    bob = User(
        username="bob_0011",
        email="bob_0011@example.com",
        password_hash=hash_password("pw"),
        full_name="Bob",
    )
    db.add_all([alice, bob])
    db.commit()

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
    app.state.manager = ConnectionManager()

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def _make_page(db: Session, user: User, page_id: str, name: str = "Test Page") -> FacebookPage:
    """Create a FacebookAccount + FacebookPage for a user."""
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id=f"fb-{user.username}-{page_id}",
        access_token_encrypted=cipher.encrypt("tok"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(account)
    db.flush()

    page = FacebookPage(
        facebook_account_id=account.id,
        page_id=page_id,
        name=name,
        is_active=True,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


def _make_conversation(
    db: Session,
    page: FacebookPage,
    psid: str,
    last_message_at: datetime | None = None,
) -> Conversation:
    conv = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
        last_message_at=last_message_at,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _make_message(
    db: Session,
    conversation: Conversation,
    mid: str,
    text: str = "hello",
    fb_ts: int = 1_700_000_000_000,
    is_from_page: bool = False,
) -> Message:
    msg = Message(
        conversation_id=conversation.id,
        mid=mid,
        event_type="message",
        is_from_page=is_from_page,
        text=text,
        fb_timestamp_ms=fb_ts,
        sent_at=datetime.fromtimestamp(fb_ts / 1000, tz=UTC),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _get_users(db: Session) -> tuple[User, User]:
    alice = db.query(User).filter(User.username == "alice_0011").one()
    bob = db.query(User).filter(User.username == "bob_0011").one()
    return alice, bob


# ===========================================================================
# Conversation list tests
# ===========================================================================


class TestListConversations:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        response = client.get("/api/v1/facebook/conversations")
        assert response.status_code == 401

    def test_empty_when_no_pages(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        response = client.get("/api/v1/facebook/conversations", headers=_auth(alice))
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["meta"]["total"] == 0

    def test_returns_own_conversations(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-alice-1")
        _make_conversation(session, page, "psid-1")
        _make_conversation(session, page, "psid-2")

        response = client.get("/api/v1/facebook/conversations", headers=_auth(alice))
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 2
        assert len(body["items"]) == 2

    def test_does_not_return_other_users_conversations(
        self, client: TestClient, session: Session
    ) -> None:
        alice, bob = _get_users(session)
        bob_page = _make_page(session, bob, "page-bob-1")
        _make_conversation(session, bob_page, "psid-bob-1")

        # Alice has no pages — should see 0 conversations
        response = client.get("/api/v1/facebook/conversations", headers=_auth(alice))
        assert response.status_code == 200
        assert response.json()["meta"]["total"] == 0

    def test_alice_cannot_see_bobs_conversations(
        self, client: TestClient, session: Session
    ) -> None:
        alice, bob = _get_users(session)
        alice_page = _make_page(session, alice, "page-alice-sec")
        bob_page = _make_page(session, bob, "page-bob-sec")
        _make_conversation(session, alice_page, "psid-alice-1")
        _make_conversation(session, bob_page, "psid-bob-1")

        response = client.get("/api/v1/facebook/conversations", headers=_auth(alice))
        assert response.status_code == 200
        body = response.json()
        # Alice should only see her own 1 conversation
        assert body["meta"]["total"] == 1
        assert body["items"][0]["page_id"] == "page-alice-sec"

    def test_filter_by_page_id(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page_a = _make_page(session, alice, "page-filter-a")
        page_b = _make_page(session, alice, "page-filter-b")
        _make_conversation(session, page_a, "psid-a1")
        _make_conversation(session, page_a, "psid-a2")
        _make_conversation(session, page_b, "psid-b1")

        response = client.get(
            "/api/v1/facebook/conversations",
            params={"page_id": "page-filter-a"},
            headers=_auth(alice),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 2
        assert all(item["page_id"] == "page-filter-a" for item in body["items"])

    def test_filter_by_unknown_page_id_returns_empty(
        self, client: TestClient, session: Session
    ) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-known")
        _make_conversation(session, page, "psid-x")

        response = client.get(
            "/api/v1/facebook/conversations",
            params={"page_id": "page-nonexistent"},
            headers=_auth(alice),
        )
        assert response.status_code == 200
        assert response.json()["meta"]["total"] == 0

    def test_sorted_newest_first_by_last_message_at(
        self, client: TestClient, session: Session
    ) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-sort")
        t_old = datetime(2025, 1, 1, tzinfo=UTC)
        t_new = datetime(2025, 6, 1, tzinfo=UTC)
        _make_conversation(session, page, "psid-old", last_message_at=t_old)
        _make_conversation(session, page, "psid-new", last_message_at=t_new)

        response = client.get("/api/v1/facebook/conversations", headers=_auth(alice))
        items = response.json()["items"]
        assert items[0]["psid"] == "psid-new"
        assert items[1]["psid"] == "psid-old"

    def test_response_shape(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-shape")
        _make_conversation(session, page, "psid-shape")

        response = client.get("/api/v1/facebook/conversations", headers=_auth(alice))
        item = response.json()["items"][0]
        assert "id" in item
        assert "page_id" in item
        assert "psid" in item
        assert "last_message_at" in item
        assert "created_at" in item
        assert "updated_at" in item

    def test_pagination_page_size(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-pag")
        for i in range(5):
            _make_conversation(session, page, f"psid-pag-{i}")

        response = client.get(
            "/api/v1/facebook/conversations",
            params={"page": 1, "page_size": 2},
            headers=_auth(alice),
        )
        body = response.json()
        assert body["meta"]["total"] == 5
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 2
        assert body["meta"]["has_next"] is True
        assert body["meta"]["has_prev"] is False
        assert len(body["items"]) == 2

    def test_pagination_second_page(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-pag2")
        for i in range(5):
            _make_conversation(session, page, f"psid-pag2-{i}")

        response = client.get(
            "/api/v1/facebook/conversations",
            params={"page": 2, "page_size": 2},
            headers=_auth(alice),
        )
        body = response.json()
        assert body["meta"]["page"] == 2
        assert body["meta"]["has_prev"] is True
        assert body["meta"]["has_next"] is True
        assert len(body["items"]) == 2

    def test_pagination_last_page(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-pag3")
        for i in range(5):
            _make_conversation(session, page, f"psid-pag3-{i}")

        response = client.get(
            "/api/v1/facebook/conversations",
            params={"page": 3, "page_size": 2},
            headers=_auth(alice),
        )
        body = response.json()
        assert body["meta"]["has_next"] is False
        assert body["meta"]["has_prev"] is True
        assert len(body["items"]) == 1  # 5 items, page 3 of 2 => 1 remaining


# ===========================================================================
# Message list tests
# ===========================================================================


class TestListMessages:
    def test_unauthenticated_returns_401(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-msg-auth")
        conv = _make_conversation(session, page, "psid-msg-auth")
        response = client.get(f"/api/v1/facebook/conversations/{conv.uuid}/messages")
        assert response.status_code == 401

    def test_nonexistent_conversation_returns_404(
        self, client: TestClient, session: Session
    ) -> None:
        alice, _ = _get_users(session)
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = client.get(
            f"/api/v1/facebook/conversations/{fake_uuid}/messages",
            headers=_auth(alice),
        )
        assert response.status_code == 404

    def test_invalid_uuid_returns_404(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        response = client.get(
            "/api/v1/facebook/conversations/not-a-uuid/messages",
            headers=_auth(alice),
        )
        assert response.status_code == 404

    def test_other_users_conversation_returns_404(
        self, client: TestClient, session: Session
    ) -> None:
        alice, bob = _get_users(session)
        bob_page = _make_page(session, bob, "page-bob-msg")
        bob_conv = _make_conversation(session, bob_page, "psid-bob-msg")

        # Alice tries to access Bob's conversation
        response = client.get(
            f"/api/v1/facebook/conversations/{bob_conv.uuid}/messages",
            headers=_auth(alice),
        )
        assert response.status_code == 404

    def test_returns_messages_for_own_conversation(
        self, client: TestClient, session: Session
    ) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-own-msg")
        conv = _make_conversation(session, page, "psid-own-msg")
        _make_message(session, conv, "mid-1", text="Hello", fb_ts=1_700_000_001_000)
        _make_message(session, conv, "mid-2", text="World", fb_ts=1_700_000_002_000)

        response = client.get(
            f"/api/v1/facebook/conversations/{conv.uuid}/messages",
            headers=_auth(alice),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 2
        assert len(body["items"]) == 2

    def test_message_response_shape(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-shape-msg")
        conv = _make_conversation(session, page, "psid-shape-msg")
        _make_message(session, conv, "mid-shape", text="hi")

        response = client.get(
            f"/api/v1/facebook/conversations/{conv.uuid}/messages",
            headers=_auth(alice),
        )
        item = response.json()["items"][0]
        assert "id" in item
        assert "conversation_id" in item
        assert "mid" in item
        assert "event_type" in item
        assert "is_from_page" in item
        assert "text" in item
        assert "sent_at" in item
        assert "created_at" in item

    def test_default_order_newest_first(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-order-msg")
        conv = _make_conversation(session, page, "psid-order-msg")
        _make_message(session, conv, "mid-old", fb_ts=1_700_000_001_000)
        _make_message(session, conv, "mid-new", fb_ts=1_700_000_009_000)

        response = client.get(
            f"/api/v1/facebook/conversations/{conv.uuid}/messages",
            headers=_auth(alice),
        )
        items = response.json()["items"]
        assert items[0]["mid"] == "mid-new"
        assert items[1]["mid"] == "mid-old"

    def test_oldest_first_order(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-oldest-msg")
        conv = _make_conversation(session, page, "psid-oldest-msg")
        _make_message(session, conv, "mid-early", fb_ts=1_700_000_001_000)
        _make_message(session, conv, "mid-late", fb_ts=1_700_000_009_000)

        response = client.get(
            f"/api/v1/facebook/conversations/{conv.uuid}/messages",
            params={"oldest_first": "true"},
            headers=_auth(alice),
        )
        items = response.json()["items"]
        assert items[0]["mid"] == "mid-early"
        assert items[1]["mid"] == "mid-late"

    def test_message_pagination(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-mpag")
        conv = _make_conversation(session, page, "psid-mpag")
        for i in range(6):
            _make_message(session, conv, f"mid-mpag-{i}", fb_ts=1_700_000_000_000 + i * 1000)

        response = client.get(
            f"/api/v1/facebook/conversations/{conv.uuid}/messages",
            params={"page": 1, "page_size": 4},
            headers=_auth(alice),
        )
        body = response.json()
        assert body["meta"]["total"] == 6
        assert body["meta"]["has_next"] is True
        assert len(body["items"]) == 4

    def test_message_pagination_second_page(self, client: TestClient, session: Session) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-mpag2")
        conv = _make_conversation(session, page, "psid-mpag2")
        for i in range(6):
            _make_message(session, conv, f"mid-mpag2-{i}", fb_ts=1_700_000_000_000 + i * 1000)

        response = client.get(
            f"/api/v1/facebook/conversations/{conv.uuid}/messages",
            params={"page": 2, "page_size": 4},
            headers=_auth(alice),
        )
        body = response.json()
        assert body["meta"]["total"] == 6
        assert body["meta"]["has_next"] is False
        assert body["meta"]["has_prev"] is True
        assert len(body["items"]) == 2

    def test_empty_conversation_returns_empty_list(
        self, client: TestClient, session: Session
    ) -> None:
        alice, _ = _get_users(session)
        page = _make_page(session, alice, "page-empty-msg")
        conv = _make_conversation(session, page, "psid-empty-msg")

        response = client.get(
            f"/api/v1/facebook/conversations/{conv.uuid}/messages",
            headers=_auth(alice),
        )
        body = response.json()
        assert body["meta"]["total"] == 0
        assert body["items"] == []
