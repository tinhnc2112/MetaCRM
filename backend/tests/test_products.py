"""Tests for the page-scoped Product catalog foundation."""

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
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-products"


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
    db.add_all(
        [
            User(
                username="alice_products",
                email="alice_products@example.com",
                password_hash=hash_password("pw"),
            ),
            User(
                username="bob_products",
                email="bob_products@example.com",
                password_hash=hash_password("pw"),
            ),
        ]
    )
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


def _users(session: Session) -> tuple[User, User]:
    return (
        session.query(User).filter(User.username == "alice_products").one(),
        session.query(User).filter(User.username == "bob_products").one(),
    )


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def _make_page(session: Session, user: User, page_id: str) -> FacebookPage:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id=f"fb-{user.username}-{page_id}",
        access_token_encrypted=cipher.encrypt("user-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(account)
    session.flush()
    page = FacebookPage(
        facebook_account_id=account.id,
        page_id=page_id,
        name=f"{user.username} Page",
        is_active=True,
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    return page


def _select_page(session: Session, user: User, page: FacebookPage) -> None:
    select_current_page(session, user, page.page_id)


def _create_product(
    client: TestClient,
    user: User,
    *,
    name: str,
    sku: str | None = None,
    sale_price: str = "10.00",
    is_active: bool = True,
) -> dict:
    response = client.post(
        "/api/v1/facebook/products",
        headers=_auth(user),
        json={
            "name": name,
            "sku": sku,
            "currency": "vnd",
            "sale_price": sale_price,
            "description": "  Catalog item  ",
            "is_active": is_active,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_create_and_get_product_normalizes_public_contract(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-product-create")
    _select_page(session, alice, page)

    created = _create_product(
        client, alice, name="  Garlic Powder  ", sku="  GP-100  ", sale_price="35000"
    )

    assert created["name"] == "Garlic Powder"
    assert created["sku"] == "GP-100"
    assert created["currency"] == "VND"
    assert created["sale_price"] == "35000.00"
    assert created["description"] == "Catalog item"
    assert "id" not in created
    assert "facebook_page_id" not in created

    response = client.get(f"/api/v1/facebook/products/{created['uuid']}", headers=_auth(alice))
    assert response.status_code == 200
    assert response.json() == created


def test_product_list_is_page_scoped_paginated_and_searchable(
    client: TestClient, session: Session
) -> None:
    alice, bob = _users(session)
    alice_page = _make_page(session, alice, "page-product-list-alice")
    bob_page = _make_page(session, bob, "page-product-list-bob")
    _select_page(session, alice, alice_page)
    _create_product(client, alice, name="Banana Chips", sku="BAN-1")
    _create_product(client, alice, name="Apple Tea", sku="APP-1", is_active=False)
    _select_page(session, bob, bob_page)
    _create_product(client, bob, name="Bob Product", sku="BOB-1")

    _select_page(session, alice, alice_page)
    first_page = client.get("/api/v1/facebook/products?page=1&page_size=1", headers=_auth(alice))
    assert first_page.status_code == 200
    assert first_page.json()["meta"] == {
        "total": 2,
        "page": 1,
        "page_size": 1,
        "has_next": True,
        "has_prev": False,
    }
    assert first_page.json()["items"][0]["name"] == "Apple Tea"

    by_name = client.get("/api/v1/facebook/products?q=banana", headers=_auth(alice))
    assert [item["sku"] for item in by_name.json()["items"]] == ["BAN-1"]
    by_sku_search = client.get("/api/v1/facebook/products?q=APP-1", headers=_auth(alice))
    assert [item["name"] for item in by_sku_search.json()["items"]] == ["Apple Tea"]
    exact_sku = client.get("/api/v1/facebook/products?sku=BAN-1", headers=_auth(alice))
    assert exact_sku.json()["meta"]["total"] == 1
    active_only = client.get("/api/v1/facebook/products?active=true", headers=_auth(alice))
    assert [item["name"] for item in active_only.json()["items"]] == ["Banana Chips"]
    assert all(item["name"] != "Bob Product" for item in first_page.json()["items"])


def test_update_and_archive_product(client: TestClient, session: Session) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-product-update")
    _select_page(session, alice, page)
    product = _create_product(client, alice, name="Old Name", sku="OLD", sale_price="10")

    updated = client.patch(
        f"/api/v1/facebook/products/{product['uuid']}",
        headers=_auth(alice),
        json={
            "name": "New Name",
            "sku": "NEW",
            "currency": "usd",
            "sale_price": "12.50",
            "description": "",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "New Name"
    assert updated.json()["sku"] == "NEW"
    assert updated.json()["currency"] == "USD"
    assert updated.json()["sale_price"] == "12.50"
    assert updated.json()["description"] is None

    archived = client.delete(f"/api/v1/facebook/products/{product['uuid']}", headers=_auth(alice))
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert (
        client.get(f"/api/v1/facebook/products/{product['uuid']}", headers=_auth(alice)).status_code
        == 404
    )
    listing = client.get("/api/v1/facebook/products", headers=_auth(alice))
    assert listing.json()["meta"]["total"] == 0


def test_cross_page_product_read_update_and_archive_are_hidden(
    client: TestClient, session: Session
) -> None:
    alice, bob = _users(session)
    alice_page = _make_page(session, alice, "page-product-cross-alice")
    bob_page = _make_page(session, bob, "page-product-cross-bob")
    _select_page(session, bob, bob_page)
    bob_product = _create_product(client, bob, name="Bob Hidden", sku="HIDDEN")
    _select_page(session, alice, alice_page)

    path = f"/api/v1/facebook/products/{bob_product['uuid']}"
    assert client.get(path, headers=_auth(alice)).status_code == 404
    assert client.patch(path, headers=_auth(alice), json={"name": "Stolen"}).status_code == 404
    assert client.delete(path, headers=_auth(alice)).status_code == 404


def test_sku_uniqueness_null_and_blank_rules(client: TestClient, session: Session) -> None:
    alice, bob = _users(session)
    alice_page = _make_page(session, alice, "page-product-sku-alice")
    bob_page = _make_page(session, bob, "page-product-sku-bob")
    _select_page(session, alice, alice_page)
    _create_product(client, alice, name="First", sku="ABC")
    duplicate = client.post(
        "/api/v1/facebook/products",
        headers=_auth(alice),
        json={"name": "Duplicate", "sku": "ABC", "sale_price": "1"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "SKU already exists for this Facebook Page"

    assert _create_product(client, alice, name="Null One", sku=None)["sku"] is None
    assert _create_product(client, alice, name="Null Two", sku=None)["sku"] is None
    assert _create_product(client, alice, name="Blank", sku="   ")["sku"] is None

    _select_page(session, bob, bob_page)
    assert _create_product(client, bob, name="Same SKU Other Page", sku="ABC")["sku"] == "ABC"


def test_product_validation_and_invalid_uuid(client: TestClient, session: Session) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-product-validation")
    _select_page(session, alice, page)

    assert (
        client.get("/api/v1/facebook/products/not-a-uuid", headers=_auth(alice)).status_code == 404
    )
    assert (
        client.post(
            "/api/v1/facebook/products",
            headers=_auth(alice),
            json={"name": "Bad Price", "sale_price": "-0.01"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/facebook/products",
            headers=_auth(alice),
            json={"name": "   ", "sale_price": "1"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/facebook/products",
            headers=_auth(alice),
            json={"name": "Bad Currency", "currency": "   ", "sale_price": "1"},
        ).status_code
        == 422
    )
