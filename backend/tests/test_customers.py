"""Tests for Messenger customer profiles and internal notes."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.customers import CustomerNote
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from app.services.facebook.crypto import TokenCipher
from app.websocket.manager import ConnectionManager
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-customer"


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

    alice = User(
        username="alice_customer",
        email="alice_customer@example.com",
        password_hash=hash_password("pw"),
        full_name="Alice Customer",
    )
    bob = User(
        username="bob_customer",
        email="bob_customer@example.com",
        password_hash=hash_password("pw"),
        full_name="Bob Customer",
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

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def _make_page(db: Session, user: User, page_id: str = "page-customer") -> FacebookPage:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id=f"fb-{user.username}-{page_id}",
        access_token_encrypted=cipher.encrypt("user-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(account)
    db.flush()

    page = FacebookPage(
        facebook_account_id=account.id,
        page_id=page_id,
        name=f"{user.username} Page",
        is_active=True,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


def _make_conversation(db: Session, page: FacebookPage, psid: str = "psid-customer") -> Conversation:
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _make_message(
    db: Session,
    conversation: Conversation,
    mid: str,
    *,
    text: str | None = "hello",
    is_from_page: bool = False,
    sent_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        mid=mid,
        event_type="message",
        is_from_page=is_from_page,
        text=text,
        fb_timestamp_ms=int((sent_at or created_at or datetime.now(UTC)).timestamp() * 1000),
        sent_at=sent_at,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _make_note(
    db: Session,
    conversation: Conversation,
    user: User,
    content: str,
    *,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> CustomerNote:
    note = CustomerNote(
        conversation_id=conversation.id,
        user_id=user.id,
        content=content,
        created_at=created_at or datetime.now(UTC),
        updated_at=updated_at or created_at or datetime.now(UTC),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def _get_users(db: Session) -> tuple[User, User]:
    alice = db.query(User).filter(User.username == "alice_customer").one()
    bob = db.query(User).filter(User.username == "bob_customer").one()
    return alice, bob


def test_get_customer_profile(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-profile")
    conversation = _make_conversation(session, page, "psid-profile")
    _make_message(
        session,
        conversation,
        "mid-profile",
        text="Customer hello",
        sent_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
    )
    _make_note(
        session,
        conversation,
        alice,
        "VIP khách miền Bắc",
        created_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
    )

    response = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["uuid"] == str(conversation.uuid)
    assert body["conversation"]["customer_psid"] == "psid-profile"
    assert body["conversation"]["unread_count"] == 1
    assert body["notes"][0]["content"] == "VIP khách miền Bắc"
    assert body["timeline"][0]["type"] == "note"


def test_create_edit_delete_note(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-notes")
    conversation = _make_conversation(session, page, "psid-notes")

    created = client.post(
        f"/api/v1/facebook/customers/{conversation.uuid}/notes",
        headers=_auth(alice),
        json={"content": "VIP khách miền Bắc"},
    )
    assert created.status_code == 200
    note_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/facebook/customers/notes/{note_id}",
        headers=_auth(alice),
        json={"content": "VIP khách miền Nam"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "VIP khách miền Nam"

    deleted = client.delete(
        f"/api/v1/facebook/customers/notes/{note_id}",
        headers=_auth(alice),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    profile = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))
    assert profile.status_code == 200
    assert profile.json()["notes"] == []


def test_wrong_page_owner_cannot_access_customer_profile_or_notes(
    client: TestClient, session: Session
) -> None:
    alice, bob = _get_users(session)
    bob_page = _make_page(session, bob, "page-bob-only")
    conversation = _make_conversation(session, bob_page, "psid-bob-only")

    profile = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))
    assert profile.status_code == 404

    note_create = client.post(
        f"/api/v1/facebook/customers/{conversation.uuid}/notes",
        headers=_auth(alice),
        json={"content": "Not allowed"},
    )
    assert note_create.status_code == 404


def test_timeline_ordering_merges_messages_and_notes_newest_first(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-timeline")
    conversation = _make_conversation(session, page, "psid-timeline")

    _make_message(
        session,
        conversation,
        "mid-old",
        text="Old message",
        sent_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
    )
    _make_note(
        session,
        conversation,
        alice,
        "Timeline note",
        created_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
    )
    _make_message(
        session,
        conversation,
        "mid-new",
        text="New message",
        sent_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
    )

    response = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))

    assert response.status_code == 200
    timeline = response.json()["timeline"]
    assert [item["type"] for item in timeline] == ["message", "note", "message"]
    assert timeline[0]["preview"] == "New message"
    assert timeline[1]["content"] == "Timeline note"
