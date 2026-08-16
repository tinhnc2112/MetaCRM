"""Tests for Messenger customer tags and simple tag segments."""

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
from app.models.messenger import Conversation
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-tags"


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
        username="alice_tags",
        email="alice_tags@example.com",
        password_hash=hash_password("pw"),
        full_name="Alice Tags",
    )
    bob = User(
        username="bob_tags",
        email="bob_tags@example.com",
        password_hash=hash_password("pw"),
        full_name="Bob Tags",
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


def _make_conversation(db: Session, page: FacebookPage, psid: str) -> Conversation:
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _get_users(db: Session) -> tuple[User, User]:
    alice = db.query(User).filter(User.username == "alice_tags").one()
    bob = db.query(User).filter(User.username == "bob_tags").one()
    return alice, bob


def _select_page(db: Session, user: User, page: FacebookPage) -> None:
    select_current_page(db, user, page.page_id)


def test_create_tag(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-create-tag")
    _select_page(session, alice, page)

    response = client.post(
        "/api/v1/facebook/customer-tags",
        headers=_auth(alice),
        json={"name": "VIP", "description": "High value customers"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "VIP"
    assert body["slug"] == "vip"
    assert body["description"] == "High value customers"
    assert body["customer_count"] == 0


def test_list_tags(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-list-tags")
    _select_page(session, alice, page)

    client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"})
    client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "Priority"})

    response = client.get("/api/v1/facebook/customer-tags", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Priority", "VIP"]
    assert all(item["customer_count"] == 0 for item in body["items"])


def test_update_tag(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-update-tag")
    _select_page(session, alice, page)

    created = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"})
    tag_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/facebook/customer-tags/{tag_id}",
        headers=_auth(alice),
        json={"name": "Priority VIP", "description": "Updated"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Priority VIP"
    assert body["slug"] == "priority-vip"
    assert body["description"] == "Updated"


def test_delete_tag(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-delete-tag")
    _select_page(session, alice, page)

    created = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"})
    tag_id = created.json()["id"]

    deleted = client.delete(f"/api/v1/facebook/customer-tags/{tag_id}", headers=_auth(alice))

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    listing = client.get("/api/v1/facebook/customer-tags", headers=_auth(alice))
    assert listing.status_code == 200
    assert listing.json()["items"] == []


def test_assign_tag_to_authorized_customer(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-assign-tag")
    _select_page(session, alice, page)
    conversation = _make_conversation(session, page, "psid-assign")
    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()

    response = client.post(
        f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}",
        headers=_auth(alice),
    )

    assert response.status_code == 200
    assert response.json()["attached"] is True

    profile = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))
    assert profile.status_code == 200
    assert [item["name"] for item in profile.json()["tags"]] == ["VIP"]

    tags = client.get("/api/v1/facebook/customer-tags", headers=_auth(alice))
    assert tags.status_code == 200
    assert tags.json()["items"][0]["customer_count"] == 1


def test_remove_tag_from_authorized_customer(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-remove-tag")
    _select_page(session, alice, page)
    conversation = _make_conversation(session, page, "psid-remove")
    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()

    client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))
    response = client.delete(
        f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}",
        headers=_auth(alice),
    )

    assert response.status_code == 200
    assert response.json()["attached"] is False

    profile = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))
    assert profile.status_code == 200
    assert profile.json()["tags"] == []


def test_duplicate_assignment_is_idempotent(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-idempotent-tag")
    _select_page(session, alice, page)
    conversation = _make_conversation(session, page, "psid-idempotent")
    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()

    first = client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))
    second = client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["attached"] is True

    profile = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))
    assert len(profile.json()["tags"]) == 1


def test_unauthorized_customer_access_is_rejected(client: TestClient, session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-alice-access")
    bob_page = _make_page(session, bob, "page-bob-access")
    _select_page(session, alice, alice_page)
    conversation = _make_conversation(session, bob_page, "psid-bob-access")
    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()

    response = client.post(
        f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}",
        headers=_auth(alice),
    )

    assert response.status_code == 404


def test_unauthorized_tag_access_is_rejected(client: TestClient, session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-alice-tag-access")
    bob_page = _make_page(session, bob, "page-bob-tag-access")
    _select_page(session, bob, bob_page)
    bob_tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(bob), json={"name": "VIP"}).json()

    _select_page(session, alice, alice_page)
    response = client.patch(
        f"/api/v1/facebook/customer-tags/{bob_tag['id']}",
        headers=_auth(alice),
        json={"name": "Renamed", "description": None},
    )

    assert response.status_code == 404


def test_filter_customers_by_tag(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-filter-tag")
    _select_page(session, alice, page)
    conversation = _make_conversation(session, page, "psid-filter-tag")
    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()
    client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))

    response = client.get(f"/api/v1/facebook/customer-tags/{tag['id']}/customers", headers=_auth(alice))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["uuid"] == str(conversation.uuid)


def test_customer_profile_returns_assigned_tags(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-profile-tags")
    _select_page(session, alice, page)
    conversation = _make_conversation(session, page, "psid-profile-tags")
    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()
    client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))

    response = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["tags"]] == ["VIP"]


def test_tag_add_remove_creates_timeline_events(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-timeline-tag")
    _select_page(session, alice, page)
    conversation = _make_conversation(session, page, "psid-timeline-tag")
    tag = client.post("/api/v1/facebook/customer-tags", headers=_auth(alice), json={"name": "VIP"}).json()

    client.post(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))
    client.delete(f"/api/v1/facebook/customers/{conversation.uuid}/tags/{tag['id']}", headers=_auth(alice))

    response = client.get(f"/api/v1/facebook/customers/{conversation.uuid}", headers=_auth(alice))

    assert response.status_code == 200
    timeline = response.json()["timeline"]
    assert [item["type"] for item in timeline] == ["tag", "tag"]
    assert [item["action"] for item in timeline] == ["removed", "added"]
    assert timeline[0]["content"] == "Tag removed: VIP"
    assert timeline[1]["content"] == "Tag added: VIP"
