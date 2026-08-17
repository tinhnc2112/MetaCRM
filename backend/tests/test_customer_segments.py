"""Tests for customer segments and advanced filtering."""

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
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-segments"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    get_settings.cache_clear()

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()

    alice = User(
        username="alice_segments",
        email="alice_segments@example.com",
        password_hash=hash_password("pw"),
        full_name="Alice Segments",
    )
    bob = User(
        username="bob_segments",
        email="bob_segments@example.com",
        password_hash=hash_password("pw"),
        full_name="Bob Segments",
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


def _make_conversation(db: Session, page: FacebookPage, psid: str, *, last_message_at: datetime | None = None) -> Conversation:
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
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
        created_at=created_at or datetime.now(UTC),
    )
    db.add(message)
    db.add(conversation)
    db.commit()
    db.refresh(message)
    db.refresh(conversation)
    return message


def _get_users(db: Session) -> tuple[User, User]:
    alice = db.query(User).filter(User.username == "alice_segments").one()
    bob = db.query(User).filter(User.username == "bob_segments").one()
    return alice, bob


def _select_page(db: Session, user: User, page: FacebookPage) -> None:
    select_current_page(db, user, page.page_id)


def _create_vip_tag(client: TestClient, user: User) -> dict:
    response = client.post("/api/v1/facebook/customer-tags", headers=_auth(user), json={"name": "VIP"})
    assert response.status_code == 200
    return response.json()


def _segment_payload(
    *,
    name: str = "VIP Customers",
    active: bool = True,
    rules: list[dict],
    description: str | None = "High value customers",
) -> dict:
    return {
        "name": name,
        "description": description,
        "active": active,
        "rules": rules,
    }


def test_create_segment_and_list_segments(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-segment-create")
    _select_page(session, alice, page)
    tag = _create_vip_tag(client, alice)
    conversation = _make_conversation(session, page, "psid-segment-create")
    _make_message(session, conversation, "mid-segment-create", sent_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC))
    client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))
    segment_payload = _segment_payload(
        rules=[{"field": "TAG", "operator": "equals", "value": tag["name"]}],
    )

    response = client.post("/api/v1/facebook/segments", headers=_auth(alice), json=segment_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "VIP Customers"
    assert body["active"] is True
    assert body["customer_count"] == 1
    assert body["rules"][0]["field"] == "TAG"
    assert body["rules"][0]["value"] == "VIP"

    listing = client.get("/api/v1/facebook/segments", headers=_auth(alice))
    assert listing.status_code == 200
    assert listing.json()["items"][0]["name"] == "VIP Customers"


def test_preview_segment_definition_matches_tag_and_date_rules(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-segment-preview")
    _select_page(session, alice, page)
    tag = _create_vip_tag(client, alice)
    conversation = _make_conversation(session, page, "psid-segment-preview")
    _make_message(session, conversation, "mid-segment-preview", sent_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC))
    client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))
    _make_conversation(session, page, "psid-segment-old")
    old_conversation = _make_conversation(session, page, "psid-segment-old-2")
    _make_message(session, old_conversation, "mid-segment-old", sent_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC))

    response = client.post(
        "/api/v1/facebook/segments/preview",
        headers=_auth(alice),
        params={"page": 1, "page_size": 20},
        json=_segment_payload(
            rules=[
                {"field": "TAG", "operator": "equals", "value": tag["name"]},
                {"field": "LAST_ACTIVITY", "operator": "after", "value": "2026-08-15T00:00:00+00:00"},
            ],
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["uuid"] == str(conversation.uuid)


def test_update_segment_and_toggle_activation(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-segment-update")
    _select_page(session, alice, page)
    tag = _create_vip_tag(client, alice)
    created = client.post(
        "/api/v1/facebook/segments",
        headers=_auth(alice),
        json=_segment_payload(rules=[{"field": "TAG", "operator": "equals", "value": tag["name"]}]),
    )
    segment_id = created.json()["id"]

    response = client.put(
        f"/api/v1/facebook/segments/{segment_id}",
        headers=_auth(alice),
        json=_segment_payload(
            name="VIP Customers Updated",
            active=False,
            rules=[{"field": "CONVERSATION_STATUS", "operator": "equals", "value": "closed"}],
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "VIP Customers Updated"
    assert body["active"] is False
    assert body["rules"][0]["field"] == "CONVERSATION_STATUS"


def test_segment_customers_endpoint_uses_and_rules(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-segment-customers")
    _select_page(session, alice, page)
    tag = _create_vip_tag(client, alice)
    matching = _make_conversation(session, page, "psid-segment-match")
    _make_message(session, matching, "mid-segment-match", sent_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    client.post(f"/api/v1/facebook/customers/{matching.uuid}/tags/{tag['id']}", headers=_auth(alice))

    non_matching = _make_conversation(session, page, "psid-segment-non-match")
    client.post(f"/api/v1/facebook/customers/{non_matching.uuid}/tags/{tag['id']}", headers=_auth(alice))

    created = client.post(
        "/api/v1/facebook/segments",
        headers=_auth(alice),
        json=_segment_payload(
            rules=[
                {"field": "TAG", "operator": "equals", "value": tag["name"]},
                {"field": "CONVERSATION_STATUS", "operator": "equals", "value": "open"},
            ],
        ),
    )
    segment_id = created.json()["id"]

    response = client.get(f"/api/v1/facebook/segments/{segment_id}/customers", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["uuid"] == str(matching.uuid)

    preview = client.post(f"/api/v1/facebook/segments/{segment_id}/preview", headers=_auth(alice))
    assert preview.status_code == 200
    assert preview.json()["meta"]["total"] == 1


def test_rule_validation_rejects_invalid_numeric_and_date_values(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-segment-validation")
    _select_page(session, alice, page)

    invalid_numeric = client.post(
        "/api/v1/facebook/segments",
        headers=_auth(alice),
        json=_segment_payload(
            rules=[{"field": "TOTAL_SPENT", "operator": "greater_than", "value": "abc"}],
        ),
    )
    assert invalid_numeric.status_code == 422

    invalid_date = client.post(
        "/api/v1/facebook/segments",
        headers=_auth(alice),
        json=_segment_payload(
            rules=[{"field": "LAST_ACTIVITY", "operator": "after", "value": "not-a-date"}],
        ),
    )
    assert invalid_date.status_code == 422


def test_segment_delete_removes_segment(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-segment-delete")
    _select_page(session, alice, page)
    tag = _create_vip_tag(client, alice)
    created = client.post(
        "/api/v1/facebook/segments",
        headers=_auth(alice),
        json=_segment_payload(rules=[{"field": "TAG", "operator": "equals", "value": tag["name"]}]),
    )
    segment_id = created.json()["id"]

    deleted = client.delete(f"/api/v1/facebook/segments/{segment_id}", headers=_auth(alice))
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    listing = client.get("/api/v1/facebook/segments", headers=_auth(alice))
    assert listing.status_code == 200
    assert listing.json()["items"] == []


def test_segment_authorization_and_ownership(client: TestClient, session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-segment-alice")
    bob_page = _make_page(session, bob, "page-segment-bob")
    _select_page(session, bob, bob_page)
    tag = _create_vip_tag(client, bob)
    created = client.post(
        "/api/v1/facebook/segments",
        headers=_auth(bob),
        json=_segment_payload(rules=[{"field": "TAG", "operator": "equals", "value": tag["name"]}]),
    )
    segment_id = created.json()["id"]

    _select_page(session, alice, alice_page)
    response = client.get(f"/api/v1/facebook/segments/{segment_id}", headers=_auth(alice))
    assert response.status_code == 404

    update = client.put(
        f"/api/v1/facebook/segments/{segment_id}",
        headers=_auth(alice),
        json=_segment_payload(rules=[{"field": "TAG", "operator": "equals", "value": tag["name"]}]),
    )
    assert update.status_code == 404

    delete = client.delete(f"/api/v1/facebook/segments/{segment_id}", headers=_auth(alice))
    assert delete.status_code == 404
