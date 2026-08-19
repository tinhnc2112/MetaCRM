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
from app.models.customer_core import Customer
from app.models.customers import CustomerNote
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.pages import select_current_page
from app.services.facebook.query_ordering import descending_with_nulls_at_end
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import mysql
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


def _select_page(db: Session, user: User, page: FacebookPage) -> None:
    select_current_page(db, user, page.page_id)


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


def _make_customer(
    db: Session,
    *,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    status: str = "ACTIVE",
    merged_into_customer_id: int | None = None,
) -> Customer:
    customer = Customer(
        name=name,
        phone=phone,
        email=email,
        status=status,
        merged_into_customer_id=merged_into_customer_id,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def _make_conversation(
    db: Session,
    page: FacebookPage,
    psid: str = "psid-customer",
    *,
    customer_id: int | None = None,
) -> Conversation:
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
        customer_id=customer_id,
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
    timestamp = sent_at or created_at or datetime.now(UTC)
    conversation.last_message_at = timestamp
    message = Message(
        conversation_id=conversation.id,
        mid=mid,
        event_type="message",
        is_from_page=is_from_page,
        text=text,
        fb_timestamp_ms=int(timestamp.timestamp() * 1000),
        sent_at=sent_at,
        created_at=created_at or timestamp,
    )
    db.add(message)
    db.add(conversation)
    db.commit()
    db.refresh(message)
    db.refresh(conversation)
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


def test_customer_list_returns_canonical_customers_sorted_and_paginated(
    client: TestClient, session: Session
) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-customer-list-alice")
    bob_page = _make_page(session, bob, "page-customer-list-bob")
    _select_page(session, alice, alice_page)

    primary_customer = _make_customer(
        session,
        name="Avery Stone",
        phone="0900000001",
        email="avery@example.com",
    )
    secondary_customer = _make_customer(
        session,
        name="Avery Stone",
        merged_into_customer_id=primary_customer.id,
    )
    other_customer = _make_customer(
        session,
        name="Brianna Fox",
        phone="0900000002",
        email="brianna@example.com",
    )
    bob_customer = _make_customer(
        session,
        name="Bob Hidden",
        email="bob-hidden@example.com",
    )

    primary_first = _make_conversation(session, alice_page, "psid-list-primary-1", customer_id=primary_customer.id)
    primary_second = _make_conversation(session, alice_page, "psid-list-primary-2", customer_id=primary_customer.id)
    other_conversation = _make_conversation(session, alice_page, "psid-list-other", customer_id=other_customer.id)
    _make_conversation(session, alice_page, "psid-list-secondary", customer_id=secondary_customer.id)
    _make_conversation(session, bob_page, "psid-list-bob", customer_id=bob_customer.id)

    _make_message(
        session,
        primary_first,
        "mid-list-primary-1",
        text="Primary old",
        sent_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
    )
    _make_message(
        session,
        primary_second,
        "mid-list-primary-2",
        text="Primary new",
        sent_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
    )
    _make_message(
        session,
        other_conversation,
        "mid-list-other",
        text="Other",
        sent_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
    )

    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()
    tag_attach = client.post(
        f"/api/v1/facebook/customers/{primary_first.uuid}/tags/{tag['id']}",
        headers=_auth(alice),
    )
    assert tag_attach.status_code == 200

    first_page = client.get(
        "/api/v1/facebook/customers",
        headers=_auth(alice),
        params={"page": 1, "page_size": 1},
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert first_body["meta"]["total"] == 2
    assert first_body["meta"]["has_next"] is True
    assert first_body["meta"]["has_prev"] is False
    assert first_body["items"][0]["uuid"] == str(primary_customer.public_id)
    assert first_body["items"][0]["conversation_count"] == 2
    assert first_body["items"][0]["tags"][0]["name"] == "VIP"

    second_page = client.get(
        "/api/v1/facebook/customers",
        headers=_auth(alice),
        params={"page": 2, "page_size": 1},
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert second_body["meta"]["has_next"] is False
    assert second_body["meta"]["has_prev"] is True
    assert second_body["items"][0]["uuid"] == str(other_customer.public_id)
    assert all(item["uuid"] != str(secondary_customer.public_id) for item in first_body["items"] + second_body["items"])
    assert all(item["uuid"] != str(bob_customer.public_id) for item in first_body["items"] + second_body["items"])


def test_customer_ordering_is_mysql_compatible_and_places_nulls_last(session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-customer-ordering-alice")
    bob_page = _make_page(session, bob, "page-customer-ordering-bob")

    newest = _make_conversation(session, alice_page, "psid-order-newest")
    older = _make_conversation(session, alice_page, "psid-order-older")
    no_timestamp = _make_conversation(session, alice_page, "psid-order-null")
    _make_conversation(session, bob_page, "psid-order-other-page")
    newest.last_message_at = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    older.last_message_at = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    session.commit()

    ordering = descending_with_nulls_at_end(Conversation.last_message_at)
    rows = (
        session.query(Conversation)
        .filter(Conversation.facebook_page_id == alice_page.id)
        .order_by(*ordering)
        .all()
    )

    assert [conversation.psid for conversation in rows] == [
        newest.psid,
        older.psid,
        no_timestamp.psid,
    ]
    statement = select(Conversation.id).order_by(*ordering)
    mysql_sql = str(statement.compile(dialect=mysql.dialect()))
    assert "NULLS LAST" not in mysql_sql.upper()
    assert "IS NULL ASC" in mysql_sql.upper()


def test_customer_list_order_search_and_page_scope_remain_unchanged(
    client: TestClient, session: Session
) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-customer-regression-alice")
    bob_page = _make_page(session, bob, "page-customer-regression-bob")
    _select_page(session, alice, alice_page)

    recent_customer = _make_customer(session, name="Needle Recent")
    older_customer = _make_customer(session, name="Older Customer")
    null_customer = _make_customer(session, name="No Timestamp Customer")
    hidden_customer = _make_customer(session, name="Needle Hidden Other Page")

    recent = _make_conversation(
        session, alice_page, "psid-regression-recent", customer_id=recent_customer.id
    )
    older = _make_conversation(
        session, alice_page, "psid-regression-older", customer_id=older_customer.id
    )
    no_timestamp = _make_conversation(
        session, alice_page, "psid-regression-null", customer_id=null_customer.id
    )
    _make_conversation(
        session, bob_page, "psid-regression-hidden", customer_id=hidden_customer.id
    )
    recent.last_message_at = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    older.last_message_at = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    no_timestamp.created_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    session.commit()

    response = client.get("/api/v1/facebook/customers", headers=_auth(alice))
    assert response.status_code == 200
    assert [item["uuid"] for item in response.json()["items"]] == [
        str(recent_customer.public_id),
        str(older_customer.public_id),
        str(null_customer.public_id),
    ]

    search_response = client.get(
        "/api/v1/facebook/customers",
        headers=_auth(alice),
        params={"q": "  needle  "},
    )
    assert search_response.status_code == 200
    assert [item["uuid"] for item in search_response.json()["items"]] == [
        str(recent_customer.public_id)
    ]


def test_customer_profile_by_customer_uuid_merges_all_conversations_and_history(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-customer-profile-uuid")
    _select_page(session, alice, page)

    customer = _make_customer(
        session,
        name="Cameron Lane",
        phone="0900000010",
        email="cameron@example.com",
    )
    first_conversation = _make_conversation(session, page, "psid-customer-profile-1", customer_id=customer.id)
    second_conversation = _make_conversation(session, page, "psid-customer-profile-2", customer_id=customer.id)

    _make_message(
        session,
        first_conversation,
        "mid-customer-profile-1",
        text="First message",
        sent_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
    )
    _make_message(
        session,
        second_conversation,
        "mid-customer-profile-2",
        text="Second message",
        sent_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
    )

    note_response = client.post(
        f"/api/v1/facebook/customers/{second_conversation.uuid}/notes",
        headers=_auth(alice),
        json={"content": "Customer note"},
    )
    assert note_response.status_code == 200

    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "Priority"}).json()
    tag_attach = client.post(
        f"/api/v1/facebook/customers/{first_conversation.uuid}/tags/{tag['id']}",
        headers=_auth(alice),
    )
    assert tag_attach.status_code == 200

    response = client.get(f"/api/v1/facebook/customers/{customer.public_id}", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["customer"]["uuid"] == str(customer.public_id)
    assert body["customer"]["conversation_count"] == 2
    assert body["conversation"]["uuid"] == str(second_conversation.uuid)
    assert [item["uuid"] for item in body["conversations"]] == [
        str(second_conversation.uuid),
        str(first_conversation.uuid),
    ]
    assert [tag_item["name"] for tag_item in body["tags"]] == ["Priority"]
    assert any(note["content"] == "Customer note" for note in body["notes"])
    assert any(item["preview"] == "First message" for item in body["timeline"])
    assert any(item["preview"] == "Second message" for item in body["timeline"])


def test_customer_profile_by_customer_uuid_rejects_merged_secondary(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-customer-profile-secondary")
    _select_page(session, alice, page)

    primary_customer = _make_customer(session, name="Primary")
    secondary_customer = _make_customer(
        session,
        name="Secondary",
        merged_into_customer_id=primary_customer.id,
    )
    _make_conversation(session, page, "psid-secondary-profile", customer_id=secondary_customer.id)

    response = client.get(f"/api/v1/facebook/customers/{secondary_customer.public_id}", headers=_auth(alice))

    assert response.status_code == 404


def test_customer_list_without_conversations_is_empty(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-empty-customer-list")
    _select_page(session, alice, page)

    response = client.get("/api/v1/facebook/customers", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["meta"]["total"] == 0


def test_customer_profile_invalid_uuid_returns_404(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-invalid-customer-uuid")
    _select_page(session, alice, page)

    response = client.get("/api/v1/facebook/customers/not-a-uuid", headers=_auth(alice))

    assert response.status_code == 404


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


def test_customer_profile_and_mutations_are_isolated_to_current_page(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page_a = _make_page(session, alice, "page-profile-scope-a")
    page_b = _make_page(session, alice, "page-profile-scope-b")
    customer = _make_customer(session, name="Shared Historical Customer")
    conversation_a = _make_conversation(
        session, page_a, "psid-profile-scope-a", customer_id=customer.id
    )
    conversation_b = _make_conversation(
        session, page_b, "psid-profile-scope-b", customer_id=customer.id
    )
    _make_message(session, conversation_a, "mid-profile-scope-a", text="Page A message")
    _make_message(session, conversation_b, "mid-profile-scope-b", text="Page B message")

    _select_page(session, alice, page_a)
    note_a = client.post(
        f"/api/v1/facebook/customers/{conversation_a.uuid}/notes",
        headers=_auth(alice),
        json={"content": "Page A note"},
    )
    tag_a = client.post(
        "/api/v1/facebook/customer-tags",
        headers=_auth(alice),
        json={"name": "Page A tag"},
    ).json()
    assert note_a.status_code == 200
    assert client.post(
        f"/api/v1/facebook/customers/{conversation_a.uuid}/tags/{tag_a['id']}",
        headers=_auth(alice),
    ).status_code == 200

    _select_page(session, alice, page_b)
    note_b = client.post(
        f"/api/v1/facebook/customers/{conversation_b.uuid}/notes",
        headers=_auth(alice),
        json={"content": "Page B note"},
    )
    tag_b = client.post(
        "/api/v1/facebook/customer-tags",
        headers=_auth(alice),
        json={"name": "Page B tag"},
    ).json()
    assert note_b.status_code == 200
    assert client.post(
        f"/api/v1/facebook/customers/{conversation_b.uuid}/tags/{tag_b['id']}",
        headers=_auth(alice),
    ).status_code == 200

    _select_page(session, alice, page_a)
    page_a_profile = client.get(
        f"/api/v1/facebook/customers/{customer.public_id}", headers=_auth(alice)
    )
    assert page_a_profile.status_code == 200
    page_a_body = page_a_profile.json()
    assert [item["uuid"] for item in page_a_body["conversations"]] == [
        str(conversation_a.uuid)
    ]
    assert [note["content"] for note in page_a_body["notes"]] == ["Page A note"]
    assert [tag["name"] for tag in page_a_body["tags"]] == ["Page A tag"]
    timeline_text = [item.get("preview") or item.get("content") for item in page_a_body["timeline"]]
    assert "Page A message" in timeline_text
    assert "Page A note" in timeline_text
    assert "Tag added: Page A tag" in timeline_text
    assert all("Page B" not in (text or "") for text in timeline_text)

    assert client.get(
        f"/api/v1/facebook/customers/{conversation_b.uuid}", headers=_auth(alice)
    ).status_code == 404
    assert client.post(
        f"/api/v1/facebook/customers/{conversation_b.uuid}/notes",
        headers=_auth(alice),
        json={"content": "Cross-Page write"},
    ).status_code == 404
    assert client.patch(
        f"/api/v1/facebook/customers/notes/{note_b.json()['id']}",
        headers=_auth(alice),
        json={"content": "Cross-Page update"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/facebook/customers/notes/{note_b.json()['id']}", headers=_auth(alice)
    ).status_code == 404
    assert client.delete(
        f"/api/v1/facebook/customers/{conversation_b.uuid}/tags/{tag_b['id']}",
        headers=_auth(alice),
    ).status_code == 404

    _select_page(session, alice, page_b)
    page_b_profile = client.get(
        f"/api/v1/facebook/customers/{customer.public_id}", headers=_auth(alice)
    )
    assert page_b_profile.status_code == 200
    page_b_body = page_b_profile.json()
    assert [item["uuid"] for item in page_b_body["conversations"]] == [
        str(conversation_b.uuid)
    ]
    assert [note["content"] for note in page_b_body["notes"]] == ["Page B note"]
    assert [tag["name"] for tag in page_b_body["tags"]] == ["Page B tag"]
