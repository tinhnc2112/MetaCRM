"""Tests for customer duplicate detection and merge workflows."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.customer_core import Customer, CustomerIdentity
from app.models.customers import (
    CustomerMerge,
    CustomerNote,
    CustomerTag,
    CustomerTagAssignment,
    CustomerTagEvent,
)
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from app.models.orders import Order
from app.services.customer_identity import CHANNEL_FACEBOOK, resolve_customer_for_conversation
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.customer_duplicates import list_customer_duplicates
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-merge"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    get_settings.cache_clear()

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()

    alice = User(
        username="alice_merge",
        email="alice_merge@example.com",
        password_hash=hash_password("pw"),
        full_name="Alice Merge",
    )
    bob = User(
        username="bob_merge",
        email="bob_merge@example.com",
        password_hash=hash_password("pw"),
        full_name="Bob Merge",
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


def _make_page(db: Session, user: User, page_id: str) -> FacebookPage:
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


def _make_conversation(
    db: Session,
    page: FacebookPage,
    psid: str,
    *,
    customer_name: str | None = None,
    customer_avatar_url: str | None = None,
    last_message_at: datetime | None = None,
) -> Conversation:
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
        customer_name=customer_name,
        customer_avatar_url=customer_avatar_url,
        last_message_at=last_message_at,
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
) -> Message:
    timestamp = sent_at or datetime.now(UTC)
    conversation.last_message_at = timestamp
    message = Message(
        conversation_id=conversation.id,
        mid=mid,
        event_type="message",
        is_from_page=is_from_page,
        text=text,
        fb_timestamp_ms=int(timestamp.timestamp() * 1000),
        sent_at=timestamp,
        created_at=timestamp,
    )
    db.add(message)
    db.add(conversation)
    db.commit()
    db.refresh(message)
    db.refresh(conversation)
    return message


def _create_tag(client: TestClient, user: User, name: str = "VIP") -> dict:
    response = client.post("/api/v1/facebook/customer-tags", headers=_auth(user), json={"name": name})
    assert response.status_code == 200
    return response.json()


def _select_page(db: Session, user: User, page: FacebookPage) -> None:
    select_current_page(db, user, page.page_id)


def _note_payload(content: str) -> dict[str, str]:
    return {"content": content}


def _merge_payload(secondary_customer_id: str) -> dict[str, str]:
    return {"secondary_customer_id": secondary_customer_id}


def test_duplicate_detection_rejects_name_only_matches(client: TestClient, session: Session) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-dup-name-only")
    _select_page(session, alice, page)
    _make_conversation(session, page, "psid-dup-1", customer_name="Taylor", customer_avatar_url="avatar-a")
    _make_conversation(session, page, "psid-dup-2", customer_name="Taylor", customer_avatar_url="avatar-b")

    response = client.get("/api/v1/facebook/customers/duplicates", headers=_auth(alice))

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_duplicate_detection_finds_matching_identity_signals(client: TestClient, session: Session) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-dup-match")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-dup-match-primary",
        customer_name="Morgan Lane",
        customer_avatar_url="https://img.example.com/avatar-1.png",
        last_message_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
    )
    duplicate = _make_conversation(
        session,
        page,
        "psid-dup-match-secondary",
        customer_name="Morgan Lane",
        customer_avatar_url="https://img.example.com/avatar-1.png",
        last_message_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
    )

    response = client.get("/api/v1/facebook/customers/duplicates", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    candidate = body["items"][0]
    assert candidate["primary_customer"]["uuid"] == str(primary.uuid)
    assert candidate["duplicate_customer"]["uuid"] == str(duplicate.uuid)
    assert candidate["confidence"] >= 0.9
    assert "customer_name" in candidate["matching_fields"]
    assert "customer_avatar_url" in candidate["matching_fields"]


def test_duplicate_detection_is_page_scoped(client: TestClient, session: Session) -> None:
    alice, bob = session.query(User).order_by(User.id.asc()).all()
    alice_page = _make_page(session, alice, "page-dup-alice")
    bob_page = _make_page(session, bob, "page-dup-bob")
    _select_page(session, alice, alice_page)
    _make_conversation(
        session,
        alice_page,
        "psid-dup-alice-1",
        customer_name="Jordan Case",
        customer_avatar_url="https://img.example.com/shared.png",
    )
    _make_conversation(
        session,
        alice_page,
        "psid-dup-alice-2",
        customer_name="Jordan Case",
        customer_avatar_url="https://img.example.com/shared.png",
    )
    _make_conversation(
        session,
        bob_page,
        "psid-dup-bob-1",
        customer_name="Jordan Case",
        customer_avatar_url="https://img.example.com/shared.png",
    )
    _make_conversation(
        session,
        bob_page,
        "psid-dup-bob-2",
        customer_name="Jordan Case",
        customer_avatar_url="https://img.example.com/shared.png",
    )
    _select_page(session, bob, bob_page)

    response = client.get("/api/v1/facebook/customers/duplicates", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert {item["primary_customer"]["uuid"] for item in body["items"]} == {str(session.query(Conversation).filter_by(psid="psid-dup-alice-1").one().uuid)}
    assert {item["duplicate_customer"]["uuid"] for item in body["items"]} == {str(session.query(Conversation).filter_by(psid="psid-dup-alice-2").one().uuid)}


def test_self_merge_is_rejected(client: TestClient, session: Session) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-merge-self")
    _select_page(session, alice, page)
    conversation = _make_conversation(
        session,
        page,
        "psid-merge-self",
        customer_name="Pat Riley",
        customer_avatar_url="https://img.example.com/pat.png",
    )

    response = client.post(
        f"/api/v1/facebook/customers/{conversation.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(conversation.uuid)),
    )

    assert response.status_code == 422


def test_successful_merge_preserves_notes_tags_messages_and_history(client: TestClient, session: Session) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-merge-success")
    _select_page(session, alice, page)
    tag = _create_tag(client, alice, "VIP Merge")
    primary = _make_conversation(
        session,
        page,
        "psid-merge-primary",
        customer_name="Avery Stone",
        customer_avatar_url="https://img.example.com/avery.png",
        last_message_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
    )
    secondary = _make_conversation(
        session,
        page,
        "psid-merge-secondary",
        customer_name="Avery Stone",
        customer_avatar_url="https://img.example.com/avery.png",
        last_message_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
    )
    _make_message(session, primary, "mid-merge-primary", text="primary hello", sent_at=datetime(2026, 8, 15, 9, 5, tzinfo=UTC))
    _make_message(session, secondary, "mid-merge-secondary", text="secondary hello", sent_at=datetime(2026, 8, 15, 10, 5, tzinfo=UTC))
    note_response = client.post(
        f"/api/v1/facebook/customers/{secondary.uuid}/notes",
        headers=_auth(alice),
        json=_note_payload("secondary note"),
    )
    assert note_response.status_code == 200
    tag_response = client.post(f"/api/v1/facebook/customers/{secondary.uuid}/tags/{tag['id']}", headers=_auth(alice))
    assert tag_response.status_code == 200
    client.post(f"/api/v1/facebook/customers/{primary.uuid}/tags/{tag['id']}", headers=_auth(alice))

    response = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["primary_customer"]["uuid"] == str(primary.uuid)
    assert body["secondary_customer"]["uuid"] == str(secondary.uuid)
    assert body["merged_by_user_id"] == alice.id

    profile = client.get(f"/api/v1/facebook/customers/{primary.uuid}", headers=_auth(alice))
    assert profile.status_code == 200
    profile_body = profile.json()
    assert any(note["content"] == "secondary note" for note in profile_body["notes"])
    assert len(profile_body["tags"]) == 1
    assert any(item["content"] == "secondary note" for item in profile_body["timeline"])
    assert any(item["preview"] == "secondary hello" for item in profile_body["timeline"])

    deleted_secondary = client.get(f"/api/v1/facebook/customers/{secondary.uuid}", headers=_auth(alice))
    assert deleted_secondary.status_code == 404

    merge_rows = session.query(CustomerMerge).all()
    assert len(merge_rows) == 1
    merge_row = merge_rows[0]
    assert merge_row.primary_conversation_id == primary.id
    assert merge_row.secondary_conversation_id == secondary.id
    assert merge_row.merged_by_user_id == alice.id


def test_merge_rolls_back_on_failure(monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-merge-rollback")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-merge-rollback-primary",
        customer_name="Charlie West",
        customer_avatar_url="https://img.example.com/charlie.png",
    )
    secondary = _make_conversation(
        session,
        page,
        "psid-merge-rollback-secondary",
        customer_name="Charlie West",
        customer_avatar_url="https://img.example.com/charlie.png",
    )
    _make_message(session, secondary, "mid-merge-rollback", text="rollback hello")
    session.add(CustomerNote(conversation_id=secondary.id, user_id=alice.id, content="rollback note"))
    session.commit()

    original_commit = session.commit

    def failing_commit() -> None:
        raise RuntimeError("forced merge failure")

    monkeypatch.setattr(session, "commit", failing_commit)

    from app.services.facebook.customer_duplicates import merge_customers

    with pytest.raises(RuntimeError):
        merge_customers(session, alice, str(primary.uuid), str(secondary.uuid))

    monkeypatch.setattr(session, "commit", original_commit)

    refreshed_primary = session.query(Conversation).filter(Conversation.id == primary.id).one()
    refreshed_secondary = session.query(Conversation).filter(Conversation.id == secondary.id).one()
    assert refreshed_primary.deleted_at is None
    assert refreshed_secondary.deleted_at is None
    assert refreshed_secondary.merged_into_conversation_id is None
    assert session.query(CustomerMerge).count() == 0
    assert session.query(Message).filter(Message.conversation_id == primary.id).count() == 0
    assert session.query(Message).filter(Message.conversation_id == secondary.id).count() == 1
    assert session.query(CustomerNote).filter(CustomerNote.conversation_id == secondary.id).count() == 1


def test_repeated_merge_returns_existing_history(client: TestClient, session: Session) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-merge-repeat")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-merge-repeat-primary",
        customer_name="Dana Field",
        customer_avatar_url="https://img.example.com/dana.png",
    )
    secondary = _make_conversation(
        session,
        page,
        "psid-merge-repeat-secondary",
        customer_name="Dana Field",
        customer_avatar_url="https://img.example.com/dana.png",
    )

    first = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )
    assert second.status_code == 200
    assert session.query(CustomerMerge).count() == 1


def test_merge_rejects_secondary_cross_page_history_before_any_mutation(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page_a = _make_page(session, alice, "page-merge-boundary-a")
    page_b = _make_page(session, alice, "page-merge-boundary-b")
    _select_page(session, alice, page_a)
    primary = _make_conversation(
        session,
        page_a,
        "psid-boundary-primary",
        customer_name="Boundary Customer",
        customer_avatar_url="https://img.example.com/boundary.png",
    )
    secondary = _make_conversation(
        session,
        page_a,
        "psid-boundary-secondary",
        customer_name="Boundary Customer",
        customer_avatar_url="https://img.example.com/boundary.png",
    )
    primary_customer_id = resolve_customer_for_conversation(session, primary)
    secondary_customer_id = resolve_customer_for_conversation(session, secondary)
    page_b_conversation = _make_conversation(
        session, page_b, "psid-boundary-secondary-page-b"
    )
    page_b_conversation.customer_id = secondary_customer_id
    tag_b = CustomerTag(facebook_page_id=page_b.id, name="Page B", slug="page-b")
    session.add(tag_b)
    session.flush()
    note_b = CustomerNote(
        conversation_id=page_b_conversation.id,
        customer_id=secondary_customer_id,
        user_id=alice.id,
        content="Page B note",
    )
    assignment_b = CustomerTagAssignment(
        conversation_id=page_b_conversation.id,
        customer_id=secondary_customer_id,
        tag_id=tag_b.id,
    )
    event_b = CustomerTagEvent(
        conversation_id=page_b_conversation.id,
        customer_id=secondary_customer_id,
        tag_id=tag_b.id,
        user_id=alice.id,
        action="added",
        tag_name_snapshot=tag_b.name,
        tag_slug_snapshot=tag_b.slug,
    )
    order_b = Order(
        facebook_page_id=page_b.id,
        customer_id=secondary_customer_id,
        conversation_id=page_b_conversation.id,
        order_number="ORD-PAGE-B",
        subtotal_amount=Decimal("10.00"),
        total_amount=Decimal("10.00"),
    )
    identity_b = CustomerIdentity(
        customer_id=secondary_customer_id,
        facebook_page_id=page_b.id,
        channel=CHANNEL_FACEBOOK,
        external_id=page_b_conversation.psid,
    )
    session.add_all([page_b_conversation, note_b, assignment_b, event_b, order_b, identity_b])
    session.commit()

    response = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )

    assert response.status_code == 422
    assert "spans multiple Facebook Pages" in response.json()["detail"]
    session.expire_all()
    assert session.get(Conversation, secondary.id).customer_id == secondary_customer_id
    assert session.get(Conversation, page_b_conversation.id).customer_id == secondary_customer_id
    assert session.get(CustomerIdentity, identity_b.id).customer_id == secondary_customer_id
    assert session.get(CustomerNote, note_b.id).customer_id == secondary_customer_id
    assert session.get(CustomerTagAssignment, assignment_b.id).customer_id == secondary_customer_id
    assert session.get(CustomerTagEvent, event_b.id).customer_id == secondary_customer_id
    assert session.get(Order, order_b.id).customer_id == secondary_customer_id
    assert session.get(CustomerIdentity, identity_b.id).facebook_page_id == page_b.id
    assert session.get(Conversation, primary.id).customer_id == primary_customer_id
    assert session.query(CustomerMerge).count() == 0


def test_merge_rejects_primary_with_other_page_presence(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page_a = _make_page(session, alice, "page-primary-footprint-a")
    page_b = _make_page(session, alice, "page-primary-footprint-b")
    _select_page(session, alice, page_a)
    primary = _make_conversation(
        session,
        page_a,
        "psid-primary-footprint",
        customer_name="Primary Footprint",
        customer_avatar_url="https://img.example.com/primary-footprint.png",
    )
    secondary = _make_conversation(
        session,
        page_a,
        "psid-secondary-footprint",
        customer_name="Primary Footprint",
        customer_avatar_url="https://img.example.com/primary-footprint.png",
    )
    primary_customer_id = resolve_customer_for_conversation(session, primary)
    secondary_customer_id = resolve_customer_for_conversation(session, secondary)
    other_page_conversation = _make_conversation(session, page_b, "psid-primary-other-page")
    other_page_conversation.customer_id = primary_customer_id
    session.commit()

    response = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )

    assert response.status_code == 422
    session.expire_all()
    assert session.get(Conversation, secondary.id).customer_id == secondary_customer_id
    assert session.get(Conversation, other_page_conversation.id).customer_id == primary_customer_id
    assert session.query(CustomerMerge).count() == 0


def test_merge_rejects_secondary_with_other_page_order_only(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page_a = _make_page(session, alice, "page-order-footprint-a")
    page_b = _make_page(session, alice, "page-order-footprint-b")
    _select_page(session, alice, page_a)
    primary = _make_conversation(
        session,
        page_a,
        "psid-order-primary",
        customer_name="Order Footprint",
        customer_avatar_url="https://img.example.com/order-footprint.png",
    )
    secondary = _make_conversation(
        session,
        page_a,
        "psid-order-secondary",
        customer_name="Order Footprint",
        customer_avatar_url="https://img.example.com/order-footprint.png",
    )
    secondary_customer_id = resolve_customer_for_conversation(session, secondary)
    resolve_customer_for_conversation(session, primary)
    order_b = Order(
        facebook_page_id=page_b.id,
        customer_id=secondary_customer_id,
        order_number="ORD-OTHER-PAGE-ONLY",
        subtotal_amount=Decimal("5.00"),
        total_amount=Decimal("5.00"),
    )
    session.add(order_b)
    session.commit()

    response = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )

    assert response.status_code == 422
    assert session.get(Order, order_b.id).customer_id == secondary_customer_id
    assert session.query(CustomerMerge).count() == 0


def test_merge_rejects_secondary_with_other_page_identity_only(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page_a = _make_page(session, alice, "page-identity-footprint-a")
    page_b = _make_page(session, alice, "page-identity-footprint-b")
    _select_page(session, alice, page_a)
    primary = _make_conversation(
        session,
        page_a,
        "psid-identity-primary",
        customer_name="Identity Footprint",
        customer_avatar_url="https://img.example.com/identity-footprint.png",
    )
    secondary = _make_conversation(
        session,
        page_a,
        "psid-identity-secondary",
        customer_name="Identity Footprint",
        customer_avatar_url="https://img.example.com/identity-footprint.png",
    )
    secondary_customer_id = resolve_customer_for_conversation(session, secondary)
    resolve_customer_for_conversation(session, primary)
    identity_b = CustomerIdentity(
        customer_id=secondary_customer_id,
        facebook_page_id=page_b.id,
        channel=CHANNEL_FACEBOOK,
        external_id="psid-identity-page-b-only",
    )
    session.add(identity_b)
    session.commit()

    response = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )

    assert response.status_code == 422
    assert session.get(CustomerIdentity, identity_b.id).customer_id == secondary_customer_id
    assert session.query(CustomerMerge).count() == 0


def test_merge_rejects_inconsistent_note_ownership_before_mutation(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-inconsistent-note")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-inconsistent-primary",
        customer_name="Inconsistent Note",
        customer_avatar_url="https://img.example.com/inconsistent-note.png",
    )
    secondary = _make_conversation(
        session,
        page,
        "psid-inconsistent-secondary",
        customer_name="Inconsistent Note",
        customer_avatar_url="https://img.example.com/inconsistent-note.png",
    )
    primary_customer_id = resolve_customer_for_conversation(session, primary)
    secondary_customer_id = resolve_customer_for_conversation(session, secondary)
    inconsistent_note = CustomerNote(
        conversation_id=primary.id,
        customer_id=secondary_customer_id,
        user_id=alice.id,
        content="Inconsistent ownership",
    )
    session.add(inconsistent_note)
    session.commit()

    response = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )

    assert response.status_code == 422
    assert "inconsistent Facebook Page ownership" in response.json()["detail"]
    session.expire_all()
    assert session.get(Conversation, primary.id).customer_id == primary_customer_id
    assert session.get(Conversation, secondary.id).customer_id == secondary_customer_id
    assert session.get(CustomerNote, inconsistent_note.id).customer_id == secondary_customer_id
    assert session.query(CustomerMerge).count() == 0


def test_reverse_retry_creates_no_self_merge_and_preserves_primary_profile(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-reverse-retry")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-reverse-primary",
        customer_name="Reverse Retry",
        customer_avatar_url="https://img.example.com/reverse.png",
    )
    secondary = _make_conversation(
        session,
        page,
        "psid-reverse-secondary",
        customer_name="Reverse Retry",
        customer_avatar_url="https://img.example.com/reverse.png",
    )

    first = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )
    exact_retry = client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    )
    reverse_retry = client.post(
        f"/api/v1/facebook/customers/{secondary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(primary.uuid)),
    )

    assert first.status_code == 200
    assert exact_retry.status_code == 200
    assert exact_retry.json()["merge_id"] == first.json()["merge_id"]
    assert reverse_retry.status_code == 409
    merges = session.query(CustomerMerge).all()
    assert len(merges) == 1
    assert merges[0].primary_customer_id != merges[0].secondary_customer_id
    assert client.get(
        f"/api/v1/facebook/customers/{primary.uuid}", headers=_auth(alice)
    ).status_code == 200
    assert client.get(
        f"/api/v1/facebook/customers/{secondary.uuid}", headers=_auth(alice)
    ).status_code == 404


def test_same_canonical_merge_is_conflict_without_any_mutation(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-same-canonical")
    _select_page(session, alice, page)
    first = _make_conversation(
        session,
        page,
        "psid-same-canonical-first",
        customer_name="Same Canonical",
        customer_avatar_url="https://img.example.com/same-canonical.png",
    )
    second = _make_conversation(
        session,
        page,
        "psid-same-canonical-second",
        customer_name="Same Canonical",
        customer_avatar_url="https://img.example.com/same-canonical.png",
    )
    customer_id = resolve_customer_for_conversation(session, first)
    second.customer_id = customer_id
    resolve_customer_for_conversation(session, second)
    tag = CustomerTag(facebook_page_id=page.id, name="Same", slug="same")
    session.add(tag)
    session.flush()
    note = CustomerNote(
        conversation_id=second.id,
        customer_id=customer_id,
        user_id=alice.id,
        content="Same-canonical note",
    )
    assignment = CustomerTagAssignment(
        conversation_id=second.id,
        customer_id=customer_id,
        tag_id=tag.id,
    )
    event = CustomerTagEvent(
        conversation_id=second.id,
        customer_id=customer_id,
        tag_id=tag.id,
        user_id=alice.id,
        action="added",
        tag_name_snapshot=tag.name,
        tag_slug_snapshot=tag.slug,
    )
    order = Order(
        facebook_page_id=page.id,
        customer_id=customer_id,
        conversation_id=second.id,
        order_number="ORD-SAME-CANONICAL",
        subtotal_amount=Decimal("1.00"),
        total_amount=Decimal("1.00"),
    )
    session.add_all([note, assignment, event, order])
    session.commit()
    identity_ids = {
        identity.id
        for identity in session.query(CustomerIdentity)
        .filter(CustomerIdentity.customer_id == customer_id)
        .all()
    }

    response = client.post(
        f"/api/v1/facebook/customers/{first.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(second.uuid)),
    )

    assert response.status_code == 409
    assert session.query(CustomerMerge).count() == 0
    assert session.get(Conversation, first.id).customer_id == customer_id
    assert session.get(Conversation, second.id).customer_id == customer_id
    assert {
        identity.id
        for identity in session.query(CustomerIdentity)
        .filter(CustomerIdentity.customer_id == customer_id)
        .all()
    } == identity_ids
    assert session.get(CustomerNote, note.id).customer_id == customer_id
    assert session.get(CustomerTagAssignment, assignment.id).customer_id == customer_id
    assert session.get(CustomerTagEvent, event.id).customer_id == customer_id
    assert session.get(Order, order.id).customer_id == customer_id
    assert client.get(
        f"/api/v1/facebook/customers/{second.uuid}", headers=_auth(alice)
    ).status_code == 200


def test_already_merged_primary_conversation_uses_canonical_root(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-canonical-primary")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-canonical-primary-a",
        customer_name="Canonical Chain",
        customer_avatar_url="https://img.example.com/canonical-chain.png",
    )
    merged_primary_input = _make_conversation(
        session,
        page,
        "psid-canonical-primary-b",
        customer_name="Canonical Chain",
        customer_avatar_url="https://img.example.com/canonical-chain.png",
    )
    third = _make_conversation(
        session,
        page,
        "psid-canonical-primary-c",
        customer_name="Canonical Chain",
        customer_avatar_url="https://img.example.com/canonical-chain.png",
    )
    canonical_id = resolve_customer_for_conversation(session, primary)
    merged_customer_id = resolve_customer_for_conversation(session, merged_primary_input)
    third_customer_id = resolve_customer_for_conversation(session, third)

    assert client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(merged_primary_input.uuid)),
    ).status_code == 200
    second_merge = client.post(
        f"/api/v1/facebook/customers/{merged_primary_input.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(third.uuid)),
    )

    assert second_merge.status_code == 200
    session.expire_all()
    assert session.get(Customer, merged_customer_id).merged_into_customer_id == canonical_id
    assert session.get(Customer, third_customer_id).merged_into_customer_id == canonical_id
    assert session.get(Customer, canonical_id).merged_into_customer_id is None
    assert session.query(CustomerMerge).count() == 2
    latest = session.query(CustomerMerge).order_by(CustomerMerge.id.desc()).first()
    assert latest is not None
    assert latest.primary_customer_id == canonical_id
    assert latest.secondary_customer_id == third_customer_id


def test_already_merged_secondary_conversation_is_rejected(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-canonical-secondary")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-canonical-secondary-a",
        customer_name="Canonical Secondary",
        customer_avatar_url="https://img.example.com/canonical-secondary.png",
    )
    merged_secondary = _make_conversation(
        session,
        page,
        "psid-canonical-secondary-b",
        customer_name="Canonical Secondary",
        customer_avatar_url="https://img.example.com/canonical-secondary.png",
    )
    third = _make_conversation(
        session,
        page,
        "psid-canonical-secondary-c",
        customer_name="Canonical Secondary",
        customer_avatar_url="https://img.example.com/canonical-secondary.png",
    )
    third_customer_id = resolve_customer_for_conversation(session, third)
    assert client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(merged_secondary.uuid)),
    ).status_code == 200

    response = client.post(
        f"/api/v1/facebook/customers/{third.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(merged_secondary.uuid)),
    )

    assert response.status_code == 409
    assert session.query(CustomerMerge).count() == 1
    assert session.get(Customer, third_customer_id).merged_into_customer_id is None
    assert session.get(Conversation, third.id).customer_id == third_customer_id


def test_duplicate_candidates_are_unique_per_canonical_customer_pair(
    session: Session,
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-canonical-candidates")
    _select_page(session, alice, page)
    first_a = _make_conversation(
        session,
        page,
        "psid-candidate-a1",
        customer_name="Canonical Candidate",
        customer_avatar_url="https://img.example.com/candidate.png",
    )
    second_a = _make_conversation(
        session,
        page,
        "psid-candidate-a2",
        customer_name="Canonical Candidate",
        customer_avatar_url="https://img.example.com/candidate.png",
    )
    first_b = _make_conversation(
        session,
        page,
        "psid-candidate-b1",
        customer_name="Canonical Candidate",
        customer_avatar_url="https://img.example.com/candidate.png",
    )
    second_b = _make_conversation(
        session,
        page,
        "psid-candidate-b2",
        customer_name="Canonical Candidate",
        customer_avatar_url="https://img.example.com/candidate.png",
    )
    customer_a = resolve_customer_for_conversation(session, first_a)
    second_a.customer_id = customer_a
    resolve_customer_for_conversation(session, second_a)
    customer_b = resolve_customer_for_conversation(session, first_b)
    second_b.customer_id = customer_b
    resolve_customer_for_conversation(session, second_b)

    result = list_customer_duplicates(session, alice)

    assert result is not None
    assert result.total == 1
    candidate = result.items[0]
    assert {candidate.primary_customer.id, candidate.duplicate_customer.id} == {
        first_a.id,
        first_b.id,
    }
    assert candidate.confidence == 0.9
    assert candidate.matching_fields == ["customer_name", "customer_avatar_url"]


def test_duplicate_candidates_disappear_after_customer_merge(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-candidates-after-merge")
    _select_page(session, alice, page)
    primary = _make_conversation(
        session,
        page,
        "psid-candidates-after-primary",
        customer_name="After Merge",
        customer_avatar_url="https://img.example.com/after-merge.png",
    )
    secondary = _make_conversation(
        session,
        page,
        "psid-candidates-after-secondary",
        customer_name="After Merge",
        customer_avatar_url="https://img.example.com/after-merge.png",
    )
    before = list_customer_duplicates(session, alice)
    assert before is not None and before.total == 1
    assert client.post(
        f"/api/v1/facebook/customers/{primary.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(secondary.uuid)),
    ).status_code == 200

    after = list_customer_duplicates(session, alice)

    assert after is not None
    assert after.total == 0


def test_legacy_same_customer_audit_does_not_hide_conversation_profile(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-legacy-self-audit")
    _select_page(session, alice, page)
    first = _make_conversation(session, page, "psid-legacy-self-first")
    second = _make_conversation(session, page, "psid-legacy-self-second")
    customer_id = resolve_customer_for_conversation(session, first)
    second.customer_id = customer_id
    session.add(
        CustomerMerge(
            facebook_page_id=page.id,
            primary_conversation_id=first.id,
            secondary_conversation_id=second.id,
            primary_customer_id=customer_id,
            secondary_customer_id=customer_id,
            merged_by_user_id=alice.id,
            duplicate_confidence=0.0,
            duplicate_reason="Legacy invalid self merge",
            matching_fields=[],
            matching_signals=[],
        )
    )
    session.commit()

    response = client.get(
        f"/api/v1/facebook/customers/{second.uuid}", headers=_auth(alice)
    )

    assert response.status_code == 200


def test_corrupted_customer_merge_cycle_is_rejected_without_audit(
    client: TestClient, session: Session
) -> None:
    alice, _ = session.query(User).order_by(User.id.asc()).all()
    page = _make_page(session, alice, "page-cycle-guard")
    _select_page(session, alice, page)
    first_customer = Customer(name="Cycle")
    second_customer = Customer(name="Cycle")
    session.add_all([first_customer, second_customer])
    session.flush()
    first_customer.merged_into_customer_id = second_customer.id
    second_customer.merged_into_customer_id = first_customer.id
    first = _make_conversation(session, page, "psid-cycle-first")
    second = _make_conversation(session, page, "psid-cycle-second")
    first.customer_id = first_customer.id
    second.customer_id = second_customer.id
    first.customer_name = second.customer_name = "Cycle"
    first.customer_avatar_url = second.customer_avatar_url = "https://img.example.com/cycle.png"
    session.commit()

    response = client.post(
        f"/api/v1/facebook/customers/{first.uuid}/merge",
        headers=_auth(alice),
        json=_merge_payload(str(second.uuid)),
    )

    assert response.status_code == 422
    assert "cycle" in response.json()["detail"].lower()
    assert session.query(CustomerMerge).count() == 0
