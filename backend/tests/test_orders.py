"""Tests for customer-centric order backend foundation."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.customer_core import Customer
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation
from app.models.orders import Order, OrderItem
from app.models.products import Product
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-orders"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    get_settings.cache_clear()

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()

    alice = User(
        username="alice_orders",
        email="alice_orders@example.com",
        password_hash=hash_password("pw"),
        full_name="Alice Orders",
    )
    bob = User(
        username="bob_orders",
        email="bob_orders@example.com",
        password_hash=hash_password("pw"),
        full_name="Bob Orders",
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


def _get_users(db: Session) -> tuple[User, User]:
    alice = db.query(User).filter(User.username == "alice_orders").one()
    bob = db.query(User).filter(User.username == "bob_orders").one()
    return alice, bob


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


def _select_page(db: Session, user: User, page: FacebookPage) -> None:
    select_current_page(db, user, page.page_id)


def _make_customer(
    db: Session,
    *,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    default_address: str | None = None,
    merged_into_customer_id: int | None = None,
) -> Customer:
    customer = Customer(
        name=name,
        phone=phone,
        email=email,
        default_address=default_address,
        status="ACTIVE",
        merged_into_customer_id=merged_into_customer_id,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def _make_conversation(
    db: Session,
    page: FacebookPage,
    *,
    psid: str,
    customer_id: int | None = None,
    customer_name: str | None = None,
    customer_avatar_url: str | None = None,
) -> Conversation:
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
        customer_id=customer_id,
        customer_name=customer_name,
        customer_avatar_url=customer_avatar_url,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _order_payload(customer_uuid: str, *, conversation_uuid: str | None = None) -> dict:
    payload = {
        "customer_uuid": customer_uuid,
        "items": [
            {"item_name": "T-shirt", "quantity": 2, "unit_price": 10.5},
            {"item_name": "Cap", "sku": "CAP-01", "quantity": 1, "unit_price": 5.0, "note": "Gift wrap"},
        ],
        "discount_amount": 1.0,
        "shipping_fee": 2.0,
        "currency": "VND",
        "note": "Call before delivery",
        "shipping_address": "123 Test Street",
    }
    if conversation_uuid is not None:
        payload["conversation_uuid"] = conversation_uuid
    return payload


def test_create_order_calculates_totals_and_snapshots(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-create")
    _select_page(session, alice, page)
    customer = _make_customer(
        session,
        name="Avery Stone",
        phone="0900000001",
        email="avery@example.com",
        default_address="Default Ship Address",
    )
    conversation = _make_conversation(session, page, psid="psid-order-create", customer_id=customer.id)

    payload = _order_payload(str(customer.public_id), conversation_uuid=str(conversation.uuid))
    payload["total_amount"] = 1.0
    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["customer_uuid"] == str(customer.public_id)
    assert body["conversation_uuid"] == str(conversation.uuid)
    assert body["order_number"].startswith("ORD-")
    assert body["customer_name_snapshot"] == "Avery Stone"
    assert body["customer_phone_snapshot"] == "0900000001"
    assert body["customer_email_snapshot"] == "avery@example.com"
    assert body["subtotal_amount"] == "26.00"
    assert body["discount_amount"] == "1.00"
    assert body["shipping_fee"] == "2.00"
    assert body["total_amount"] == "27.00"
    assert body["item_count"] == 2
    assert body["shipping_address"] == "123 Test Street"
    assert body["note"] == "Call before delivery"
    assert "id" not in body
    assert "customer_id" not in body
    assert "facebook_page_id" not in body
    assert "conversation_id" not in body
    assert "created_by_id" not in body
    assert len(body["items"]) == 2
    assert body["items"][0]["line_total"] == "21.00"
    assert body["items"][0]["product_uuid"] is None
    assert body["items"][1]["line_total"] == "5.00"
    assert "id" not in body["items"][0]
    assert "order_id" not in body["items"][0]

    order_row = session.query(Order).filter(Order.public_id == UUID(body["uuid"])).one()
    assert order_row.customer_id == customer.id
    assert order_row.conversation_id == conversation.id
    assert session.query(OrderItem).filter(OrderItem.order_id == order_row.id).count() == 2


def test_product_backed_items_snapshot_defaults_and_price_override(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-product")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Product Buyer")
    _make_conversation(session, page, psid="psid-order-product", customer_id=customer.id)
    product = Product(
        facebook_page_id=page.id,
        name="Garlic Powder 100g",
        sku="GP100",
        currency="VND",
        sale_price=Decimal("35000.00"),
        is_active=True,
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [
                {"product_uuid": str(product.public_id), "quantity": 2},
                {
                    "product_uuid": str(product.public_id),
                    "item_name": "Ignored client name",
                    "sku": "IGNORED",
                    "quantity": 1,
                    "unit_price": 30000,
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subtotal_amount"] == "100000.00"
    assert body["total_amount"] == "100000.00"
    assert [item["item_name"] for item in body["items"]] == ["Garlic Powder 100g", "Garlic Powder 100g"]
    assert [item["sku"] for item in body["items"]] == ["GP100", "GP100"]
    assert [item["unit_price"] for item in body["items"]] == ["35000.00", "30000.00"]
    assert all(item["product_uuid"] == str(product.public_id) for item in body["items"])
    order_row = session.query(Order).filter(Order.public_id == UUID(body["uuid"])).one()
    rows = session.query(OrderItem).filter(OrderItem.order_id == order_row.id).all()
    assert all(item.product_id == product.id for item in rows)
    session.refresh(product)
    assert product.sale_price == Decimal("35000.00")

    negative_override = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [
                {"product_uuid": str(product.public_id), "quantity": 1, "unit_price": "-0.01"}
            ],
        },
    )
    assert negative_override.status_code == 422


def test_product_backed_order_rejects_numeric_overflow(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-product-overflow")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Overflow Buyer")
    _make_conversation(session, page, psid="psid-order-product-overflow", customer_id=customer.id)
    product = Product(
        facebook_page_id=page.id,
        name="Maximum Price",
        currency="VND",
        sale_price=Decimal("9999999999.99"),
        is_active=True,
    )
    session.add(product)
    session.commit()

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"product_uuid": str(product.public_id), "quantity": 2}],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "line_total exceeds Numeric(12, 2) capacity"


def test_product_updates_and_archive_do_not_change_order_snapshots(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-product-history")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="History Buyer")
    _make_conversation(session, page, psid="psid-order-product-history", customer_id=customer.id)
    product = Product(
        facebook_page_id=page.id,
        name="Original Name",
        sku="ORIGINAL",
        currency="VND",
        sale_price=Decimal("25.00"),
        is_active=True,
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"product_uuid": str(product.public_id), "quantity": 1}],
        },
    )
    assert created.status_code == 200
    order_uuid = created.json()["uuid"]

    updated = client.patch(
        f"/api/v1/facebook/products/{product.public_id}",
        headers=_auth(alice),
        json={"name": "New Name", "sku": "NEW-SKU", "sale_price": "40.00"},
    )
    assert updated.status_code == 200
    detail = client.get(f"/api/v1/facebook/orders/{order_uuid}", headers=_auth(alice)).json()
    assert detail["items"][0]["item_name"] == "Original Name"
    assert detail["items"][0]["sku"] == "ORIGINAL"
    assert detail["items"][0]["unit_price"] == "25.00"

    archived = client.delete(f"/api/v1/facebook/products/{product.public_id}", headers=_auth(alice))
    assert archived.status_code == 200
    archived_detail = client.get(f"/api/v1/facebook/orders/{order_uuid}", headers=_auth(alice))
    assert archived_detail.status_code == 200
    assert archived_detail.json()["items"][0]["product_uuid"] == str(product.public_id)
    rejected = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"product_uuid": str(product.public_id), "quantity": 1}],
        },
    )
    assert rejected.status_code == 404


def test_inactive_cross_page_and_currency_mismatched_products_are_rejected(
    client: TestClient,
    session: Session,
) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-order-product-alice")
    bob_page = _make_page(session, bob, "page-order-product-bob")
    _select_page(session, alice, alice_page)
    customer = _make_customer(session, name="Scoped Product Buyer")
    _make_conversation(session, alice_page, psid="psid-order-product-alice", customer_id=customer.id)
    inactive = Product(
        facebook_page_id=alice_page.id,
        name="Inactive",
        currency="VND",
        sale_price=Decimal("1.00"),
        is_active=False,
    )
    usd_product = Product(
        facebook_page_id=alice_page.id,
        name="USD Product",
        currency="USD",
        sale_price=Decimal("1.00"),
        is_active=True,
    )
    cross_page = Product(
        facebook_page_id=bob_page.id,
        name="Cross Page",
        currency="VND",
        sale_price=Decimal("1.00"),
        is_active=True,
    )
    session.add_all([inactive, usd_product, cross_page])
    session.commit()

    for product in (inactive, cross_page):
        response = client.post(
            "/api/v1/facebook/orders",
            headers=_auth(alice),
            json={
                "customer_uuid": str(customer.public_id),
                "items": [{"product_uuid": str(product.public_id), "quantity": 1}],
            },
        )
        assert response.status_code == 404

    currency_mismatch = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "currency": "VND",
            "items": [{"product_uuid": str(usd_product.public_id), "quantity": 1}],
        },
    )
    assert currency_mismatch.status_code == 422


def test_create_order_rejects_cross_page_customer(client: TestClient, session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-order-alice")
    bob_page = _make_page(session, bob, "page-order-bob")
    _select_page(session, alice, alice_page)
    bob_customer = _make_customer(session, name="Bob Visible", email="bob@example.com")
    _make_conversation(session, bob_page, psid="psid-bob-cross", customer_id=bob_customer.id)

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(bob_customer.public_id)),
    )

    assert response.status_code == 404


def test_create_order_rejects_cross_page_conversation(client: TestClient, session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-order-conv-alice")
    bob_page = _make_page(session, bob, "page-order-conv-bob")
    _select_page(session, alice, alice_page)
    customer = _make_customer(session, name="Alice Customer", email="alice@example.com")
    bob_customer = _make_customer(session, name="Bob Customer", email="bob@example.com")
    bob_conversation = _make_conversation(session, bob_page, psid="psid-bob-conv", customer_id=bob_customer.id)
    _make_conversation(session, alice_page, psid="psid-alice-conv", customer_id=customer.id)

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id), conversation_uuid=str(bob_conversation.uuid)),
    )

    assert response.status_code == 404


def test_orders_are_page_scoped(client: TestClient, session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-order-list-alice")
    bob_page = _make_page(session, bob, "page-order-list-bob")
    _select_page(session, alice, alice_page)
    alice_customer = _make_customer(session, name="Alice Buyer", email="alice-buyer@example.com")
    bob_customer = _make_customer(session, name="Bob Buyer", email="bob-buyer@example.com")
    _make_conversation(session, alice_page, psid="psid-order-list-alice", customer_id=alice_customer.id)
    _make_conversation(session, bob_page, psid="psid-order-list-bob", customer_id=bob_customer.id)

    alice_response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(alice_customer.public_id)),
    )
    assert alice_response.status_code == 200

    _select_page(session, bob, bob_page)
    bob_response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(bob),
        json=_order_payload(str(bob_customer.public_id)),
    )
    assert bob_response.status_code == 200

    _select_page(session, alice, alice_page)
    list_response = client.get("/api/v1/facebook/orders", headers=_auth(alice))
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["customer_uuid"] == str(alice_customer.public_id)
    assert body["items"][0]["item_count"] == 2


def test_get_order_is_page_scoped(client: TestClient, session: Session) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-order-get-alice")
    bob_page = _make_page(session, bob, "page-order-get-bob")
    _select_page(session, alice, alice_page)
    alice_customer = _make_customer(session, name="Alice Get", email="alice-get@example.com")
    bob_customer = _make_customer(session, name="Bob Get", email="bob-get@example.com")
    _make_conversation(session, alice_page, psid="psid-order-get-alice", customer_id=alice_customer.id)
    _make_conversation(session, bob_page, psid="psid-order-get-bob", customer_id=bob_customer.id)

    alice_order = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(alice_customer.public_id)),
    ).json()
    _select_page(session, bob, bob_page)
    bob_order = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(bob),
        json=_order_payload(str(bob_customer.public_id)),
    ).json()

    response = client.get(f"/api/v1/facebook/orders/{alice_order['uuid']}", headers=_auth(alice))
    assert response.status_code == 200
    detail = response.json()
    assert detail["uuid"] == alice_order["uuid"]
    assert detail["item_count"] == 2
    assert len(detail["items"]) == 2
    assert detail["items"][0]["item_name"] == "T-shirt"
    assert detail["items"][0]["quantity"] == 2
    assert detail["items"][0]["unit_price"] == "10.50"
    assert detail["items"][0]["line_total"] == "21.00"
    assert "id" not in detail
    assert "customer_id" not in detail
    assert "order_id" not in detail["items"][0]

    wrong_page = client.get(f"/api/v1/facebook/orders/{bob_order['uuid']}", headers=_auth(alice))
    assert wrong_page.status_code == 404


def test_customer_order_history_endpoint(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-history")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="History Customer", email="history@example.com")
    conversation = _make_conversation(session, page, psid="psid-order-history", customer_id=customer.id)

    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id), conversation_uuid=str(conversation.uuid)),
    )
    assert created.status_code == 200

    response = client.get(f"/api/v1/facebook/customers/{customer.public_id}/orders", headers=_auth(alice))
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["customer_uuid"] == str(customer.public_id)
    assert body["items"][0]["item_count"] == 2


def test_order_list_and_history_include_correct_item_counts(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-item-count")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Item Count Customer", email="item-count@example.com")
    _make_conversation(session, page, psid="psid-order-item-count", customer_id=customer.id)

    first = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id)),
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"item_name": "Sticker", "quantity": 1, "unit_price": 3.0}],
        },
    )
    assert second.status_code == 200

    all_orders = client.get("/api/v1/facebook/orders", headers=_auth(alice))
    assert all_orders.status_code == 200
    list_counts = {item["uuid"]: item["item_count"] for item in all_orders.json()["items"]}
    assert list_counts[first.json()["uuid"]] == 2
    assert list_counts[second.json()["uuid"]] == 1

    history = client.get(f"/api/v1/facebook/customers/{customer.public_id}/orders", headers=_auth(alice))
    assert history.status_code == 200
    history_counts = {item["uuid"]: item["item_count"] for item in history.json()["items"]}
    assert history_counts[first.json()["uuid"]] == 2
    assert history_counts[second.json()["uuid"]] == 1


def test_customer_order_summary_is_page_scoped_and_excludes_cancelled_spend(
    client: TestClient,
    session: Session,
) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-order-summary-alice")
    bob_page = _make_page(session, bob, "page-order-summary-bob")
    _select_page(session, alice, alice_page)
    customer = _make_customer(session, name="Summary Customer", email="summary@example.com")
    bob_customer = _make_customer(session, name="Bob Summary", email="bob-summary@example.com")
    _make_conversation(session, alice_page, psid="psid-order-summary-alice", customer_id=customer.id)
    _make_conversation(session, bob_page, psid="psid-order-summary-bob", customer_id=bob_customer.id)

    active_order = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id)),
    )
    assert active_order.status_code == 200
    cancelled_order = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id)),
    )
    assert cancelled_order.status_code == 200
    cancel_response = client.patch(
        f"/api/v1/facebook/orders/{cancelled_order.json()['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert cancel_response.status_code == 200

    summary = client.get(f"/api/v1/facebook/customers/{customer.public_id}/orders/summary", headers=_auth(alice))
    assert summary.status_code == 200
    body = summary.json()
    assert body["order_count"] == 2
    assert body["total_spend"] == "27.00"
    assert body["latest_order_at"] is not None

    wrong_page_summary = client.get(
        f"/api/v1/facebook/customers/{bob_customer.public_id}/orders/summary",
        headers=_auth(alice),
    )
    assert wrong_page_summary.status_code == 404


def test_invalid_status_filters_return_422(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-invalid-status")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Invalid Status Customer", email="invalid-status@example.com")
    _make_conversation(session, page, psid="psid-order-invalid-status", customer_id=customer.id)

    list_response = client.get(
        "/api/v1/facebook/orders?status=unknown",
        headers=_auth(alice),
    )
    assert list_response.status_code == 422

    history_response = client.get(
        f"/api/v1/facebook/customers/{customer.public_id}/orders?status=unknown",
        headers=_auth(alice),
    )
    assert history_response.status_code == 422


def test_invalid_uuid_handling_returns_404(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-invalid")
    _select_page(session, alice, page)

    response = client.get("/api/v1/facebook/orders/not-a-uuid", headers=_auth(alice))
    assert response.status_code == 404


def test_update_order_status_payment_shipping_and_note(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-update")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Update Customer", email="update@example.com")
    _make_conversation(session, page, psid="psid-order-update", customer_id=customer.id)

    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id)),
    )
    assert created.status_code == 200
    order_uuid = created.json()["uuid"]

    updated = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={
            "status": "confirmed",
            "payment_status": "paid",
            "shipping_status": "packed",
            "note": "Ready to ship",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["status"] == "confirmed"
    assert body["payment_status"] == "paid"
    assert body["shipping_status"] == "packed"
    assert body["note"] == "Ready to ship"


def test_update_order_recalculates_totals_and_rejects_negative_total(
    client: TestClient,
    session: Session,
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-update-totals")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Update Totals Customer", email="update-totals@example.com")
    _make_conversation(session, page, psid="psid-order-update-totals", customer_id=customer.id)

    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id)),
    )
    assert created.status_code == 200
    order_uuid = created.json()["uuid"]

    updated = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={"discount_amount": 5.0, "shipping_fee": 1.0},
    )
    assert updated.status_code == 200
    assert updated.json()["subtotal_amount"] == "26.00"
    assert updated.json()["discount_amount"] == "5.00"
    assert updated.json()["shipping_fee"] == "1.00"
    assert updated.json()["total_amount"] == "22.00"

    overflow = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={"shipping_fee": "9999999999.99"},
    )
    assert overflow.status_code == 422
    session.rollback()

    rejected = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={"discount_amount": 999.0},
    )
    assert rejected.status_code == 422


def test_cancelled_order_cannot_be_reopened(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-cancelled")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Cancelled Customer", email="cancelled@example.com")
    _make_conversation(session, page, psid="psid-order-cancelled", customer_id=customer.id)

    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id)),
    )
    assert created.status_code == 200
    order_uuid = created.json()["uuid"]

    cancelled = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_at"] is not None

    reopened = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    assert reopened.status_code == 422


def test_invalid_totals_are_rejected(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-invalid-totals")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Totals Customer", email="totals@example.com")
    _make_conversation(session, page, psid="psid-order-invalid-totals", customer_id=customer.id)

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"item_name": "Bad", "quantity": 0, "unit_price": 1.0}],
        },
    )
    assert response.status_code == 422


def test_merge_transfers_orders_to_primary_customer(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-merge")
    _select_page(session, alice, page)
    primary = _make_customer(
        session,
        name="Merge Primary",
        email="merge-primary@example.com",
    )
    secondary = _make_customer(
        session,
        name="Merge Primary",
        email="merge-primary@example.com",
    )
    primary_conversation = _make_conversation(
        session,
        page,
        psid="psid-order-merge-primary",
        customer_id=primary.id,
        customer_name="Merge Primary",
        customer_avatar_url="https://img.example.com/avatar.png",
    )
    secondary_conversation = _make_conversation(
        session,
        page,
        psid="psid-order-merge-secondary",
        customer_id=secondary.id,
        customer_name="Merge Primary",
        customer_avatar_url="https://img.example.com/avatar.png",
    )

    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(secondary.public_id), conversation_uuid=str(secondary_conversation.uuid)),
    )
    assert created.status_code == 200
    order_uuid = created.json()["uuid"]

    merge_response = client.post(
        f"/api/v1/facebook/customers/{primary_conversation.uuid}/merge",
        headers=_auth(alice),
        json={"secondary_customer_id": str(secondary_conversation.uuid)},
    )
    assert merge_response.status_code == 200

    history = client.get(f"/api/v1/facebook/customers/{primary.public_id}/orders", headers=_auth(alice))
    assert history.status_code == 200
    assert history.json()["meta"]["total"] == 1
    assert history.json()["items"][0]["uuid"] == order_uuid

    secondary_history = client.get(
        f"/api/v1/facebook/customers/{secondary.public_id}/orders",
        headers=_auth(alice),
    )
    assert secondary_history.status_code == 404

    order_row = session.query(Order).filter(Order.public_id == UUID(order_uuid)).one()
    assert order_row.customer_id == primary.id


def test_customer_order_history_isolated_when_customer_spans_pages(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page_a = _make_page(session, alice, "page-order-history-scope-a")
    page_b = _make_page(session, alice, "page-order-history-scope-b")
    customer = _make_customer(session, name="Cross Page Order Customer")
    conversation_a = _make_conversation(
        session, page_a, psid="psid-order-history-a", customer_id=customer.id
    )
    conversation_b = _make_conversation(
        session, page_b, psid="psid-order-history-b", customer_id=customer.id
    )
    order_a = Order(
        facebook_page_id=page_a.id,
        customer_id=customer.id,
        conversation_id=conversation_a.id,
        order_number="ORD-HISTORY-A",
        subtotal_amount=Decimal("11.00"),
        total_amount=Decimal("11.00"),
    )
    order_b = Order(
        facebook_page_id=page_b.id,
        customer_id=customer.id,
        conversation_id=conversation_b.id,
        order_number="ORD-HISTORY-B",
        subtotal_amount=Decimal("22.00"),
        total_amount=Decimal("22.00"),
    )
    inconsistent_order = Order(
        facebook_page_id=page_a.id,
        customer_id=customer.id,
        conversation_id=conversation_b.id,
        order_number="ORD-INCONSISTENT-CONVERSATION",
        subtotal_amount=Decimal("99.00"),
        total_amount=Decimal("99.00"),
    )
    session.add_all([order_a, order_b, inconsistent_order])
    session.commit()

    _select_page(session, alice, page_a)
    page_a_history = client.get(
        f"/api/v1/facebook/customers/{customer.public_id}/orders", headers=_auth(alice)
    )
    page_a_summary = client.get(
        f"/api/v1/facebook/customers/{customer.public_id}/orders/summary",
        headers=_auth(alice),
    )
    assert page_a_history.status_code == 200
    assert [item["order_number"] for item in page_a_history.json()["items"]] == [
        "ORD-HISTORY-A"
    ]
    assert page_a_summary.json()["order_count"] == 1
    assert page_a_summary.json()["total_spend"] == "11.00"
    assert client.get(
        f"/api/v1/facebook/orders/{order_b.public_id}", headers=_auth(alice)
    ).status_code == 404
    assert client.get(
        f"/api/v1/facebook/orders/{inconsistent_order.public_id}", headers=_auth(alice)
    ).status_code == 404

    _select_page(session, alice, page_b)
    page_b_history = client.get(
        f"/api/v1/facebook/customers/{customer.public_id}/orders", headers=_auth(alice)
    )
    assert page_b_history.status_code == 200
    assert [item["order_number"] for item in page_b_history.json()["items"]] == [
        "ORD-HISTORY-B"
    ]
