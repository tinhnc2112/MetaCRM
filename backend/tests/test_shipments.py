"""Tests for carrier-neutral Shipment foundation."""

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
from app.models.inventory import ProductInventory, StockMovement
from app.models.messenger import Conversation
from app.models.orders import Order
from app.models.products import Product
from app.models.shipments import Shipment, ShipmentEvent
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.orders import get_order_timeline
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-shipments"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    db.add_all(
        [
            User(
                username="alice_shipments",
                email="alice_shipments@example.com",
                password_hash=hash_password("pw"),
                full_name="Alice Shipments",
            ),
            User(
                username="bob_shipments",
                email="bob_shipments@example.com",
                password_hash=hash_password("pw"),
                full_name="Bob Shipments",
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


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def _users(db: Session) -> tuple[User, User]:
    return (
        db.query(User).filter(User.username == "alice_shipments").one(),
        db.query(User).filter(User.username == "bob_shipments").one(),
    )


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


def _customer(db: Session, page: FacebookPage, suffix: str) -> Customer:
    customer = Customer(name=f"Shipment Buyer {suffix}", phone="0901234567", status="ACTIVE")
    db.add(customer)
    db.flush()
    db.add(
        Conversation(
            facebook_page_id=page.id,
            page_id=page.page_id,
            psid=f"psid-shipment-{suffix}",
            customer_id=customer.id,
        )
    )
    db.commit()
    db.refresh(customer)
    return customer


def _complete_destination(label: str = "Original") -> dict[str, str]:
    return {
        "recipient_name": f"{label} Recipient",
        "recipient_phone": "0901234567",
        "address_line": f"{label} 123 Street",
        "ward": "Ward 1",
        "district": "District 1",
        "province": "HCMC",
        "country_code": "VN",
        "note": f"{label} note",
    }


def _create_confirmed_order(
    client: TestClient,
    user: User,
    customer: Customer,
    *,
    destination: dict[str, str] | None = None,
    product_uuid: str | None = None,
) -> dict:
    item = (
        {"product_uuid": product_uuid, "quantity": 2}
        if product_uuid is not None
        else {"item_name": "Shipment item", "quantity": 2, "unit_price": 10}
    )
    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(user),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [item],
            "shipping_destination": destination or _complete_destination(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_shipment(client: TestClient, user: User, order_uuid: str) -> dict:
    response = client.post(
        f"/api/v1/facebook/orders/{order_uuid}/shipments",
        headers=_auth(user),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _patch_shipment(client: TestClient, user: User, shipment_uuid: str, status: str) -> dict:
    response = client.patch(
        f"/api/v1/facebook/shipments/{shipment_uuid}/status",
        headers=_auth(user),
        json={"status": status},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_list_get_snapshot_page_safe_and_stock_neutral(client: TestClient, session: Session) -> None:
    alice, bob = _users(session)
    page_a = _make_page(session, alice, "page-shipment-create-a")
    page_b = _make_page(session, bob, "page-shipment-create-b")
    _select_page(session, alice, page_a)
    customer = _customer(session, page_a, "create")
    order = _create_confirmed_order(client, alice, customer)
    movement_count = session.query(StockMovement).count()

    shipment = _create_shipment(client, alice, order["uuid"])

    assert shipment["uuid"]
    assert shipment["order_uuid"] == order["uuid"]
    assert shipment["shipment_number"].startswith("SHP-")
    assert shipment["status"] == "ready"
    assert shipment["tracking_number"] is None
    assert shipment["recipient"]["recipient_name"] == "Original Recipient"
    assert shipment["recipient"]["address_line"] == "Original 123 Street"
    assert "id" not in shipment and "order_id" not in shipment
    assert session.query(StockMovement).count() == movement_count
    assert session.query(ShipmentEvent).filter_by(event_type="CREATED").count() == 1

    listed = client.get(
        f"/api/v1/facebook/orders/{order['uuid']}/shipments",
        headers=_auth(alice),
    )
    detail = client.get(
        f"/api/v1/facebook/shipments/{shipment['uuid']}",
        headers=_auth(alice),
    )
    assert listed.status_code == detail.status_code == 200
    assert listed.json()["items"][0]["uuid"] == shipment["uuid"]
    assert detail.json()["uuid"] == shipment["uuid"]
    assert client.get(
        f"/api/v1/facebook/orders/{order['uuid']}",
        headers=_auth(alice),
    ).json()["shipping_status"] == "pending"

    _select_page(session, bob, page_b)
    assert client.get(
        f"/api/v1/facebook/shipments/{shipment['uuid']}",
        headers=_auth(bob),
    ).status_code == 404
    assert client.get(
        f"/api/v1/facebook/orders/{order['uuid']}/shipments",
        headers=_auth(bob),
    ).status_code == 404


@pytest.mark.parametrize("order_status", ["draft", "cancelled"])
def test_create_rejects_incompatible_order_statuses(
    client: TestClient, session: Session, order_status: str
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, f"page-shipment-reject-{order_status}")
    _select_page(session, alice, page)
    customer = _customer(session, page, order_status)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "draft",
            "items": [{"item_name": "Draft item", "quantity": 1, "unit_price": 1}],
            "shipping_destination": _complete_destination(),
        },
    ).json()
    if order_status == "cancelled":
        assert client.patch(
            f"/api/v1/facebook/orders/{created['uuid']}",
            headers=_auth(alice),
            json={"status": "cancelled"},
        ).status_code == 200

    response = client.post(
        f"/api/v1/facebook/orders/{created['uuid']}/shipments",
        headers=_auth(alice),
    )
    assert response.status_code == 409
    assert session.query(Shipment).count() == 0


def test_create_rejects_incomplete_destination(client: TestClient, session: Session) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-shipment-incomplete")
    _select_page(session, alice, page)
    customer = _customer(session, page, "incomplete")
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [{"item_name": "Incomplete item", "quantity": 1, "unit_price": 1}],
            "shipping_destination": {"province": "HCMC"},
        },
    ).json()

    response = client.post(
        f"/api/v1/facebook/orders/{created['uuid']}/shipments",
        headers=_auth(alice),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Order shipping destination is incomplete"


def test_lifecycle_matrix_same_state_and_aggregation(client: TestClient, session: Session) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-shipment-lifecycle")
    _select_page(session, alice, page)
    customer = _customer(session, page, "lifecycle")
    order = _create_confirmed_order(client, alice, customer)
    shipment = _create_shipment(client, alice, order["uuid"])
    event_count = session.query(ShipmentEvent).count()

    same = _patch_shipment(client, alice, shipment["uuid"], "ready")
    assert same["status"] == "ready"
    assert session.query(ShipmentEvent).count() == event_count

    packed = _patch_shipment(client, alice, shipment["uuid"], "packed")
    assert packed["status"] == "packed"
    assert client.get(f"/api/v1/facebook/orders/{order['uuid']}", headers=_auth(alice)).json()["shipping_status"] == "packed"
    invalid = client.patch(
        f"/api/v1/facebook/shipments/{shipment['uuid']}/status",
        headers=_auth(alice),
        json={"status": "delivered"},
    )
    assert invalid.status_code == 409
    assert session.query(ShipmentEvent).filter_by(event_type="DELIVERED").count() == 0

    shipped = _patch_shipment(client, alice, shipment["uuid"], "shipped")
    assert shipped["status"] == "shipped"
    assert client.get(f"/api/v1/facebook/orders/{order['uuid']}", headers=_auth(alice)).json()["shipping_status"] == "shipped"
    delivered = _patch_shipment(client, alice, shipment["uuid"], "delivered")
    assert delivered["status"] == "delivered"
    assert client.get(f"/api/v1/facebook/orders/{order['uuid']}", headers=_auth(alice)).json()["shipping_status"] == "delivered"
    terminal = client.patch(
        f"/api/v1/facebook/shipments/{shipment['uuid']}/status",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert terminal.status_code == 409


def test_cancelled_replacement_snapshot_and_order_safety(client: TestClient, session: Session) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-shipment-replacement")
    _select_page(session, alice, page)
    customer = _customer(session, page, "replacement")
    order = _create_confirmed_order(client, alice, customer)
    first = _create_shipment(client, alice, order["uuid"])

    blocked_cancel = client.patch(
        f"/api/v1/facebook/orders/{order['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert blocked_cancel.status_code == 409
    blocked_edit = client.patch(
        f"/api/v1/facebook/orders/{order['uuid']}/shipping-address",
        headers=_auth(alice),
        json=_complete_destination("New"),
    )
    assert blocked_edit.status_code == 409
    manual_shipping = client.patch(
        f"/api/v1/facebook/orders/{order['uuid']}",
        headers=_auth(alice),
        json={"shipping_status": "packed"},
    )
    assert manual_shipping.status_code == 409

    cancelled = _patch_shipment(client, alice, first["uuid"], "cancelled")
    assert cancelled["status"] == "cancelled"
    assert client.get(f"/api/v1/facebook/orders/{order['uuid']}", headers=_auth(alice)).json()["shipping_status"] == "cancelled"
    edited = client.patch(
        f"/api/v1/facebook/orders/{order['uuid']}/shipping-address",
        headers=_auth(alice),
        json=_complete_destination("New"),
    )
    assert edited.status_code == 200
    second = _create_shipment(client, alice, order["uuid"])
    assert second["recipient"]["address_line"] == "New 123 Street"
    assert second["status"] == "ready"
    assert client.get(f"/api/v1/facebook/orders/{order['uuid']}", headers=_auth(alice)).json()["shipping_status"] == "pending"
    old = client.get(f"/api/v1/facebook/shipments/{first['uuid']}", headers=_auth(alice)).json()
    assert old["status"] == "cancelled"
    assert old["recipient"]["address_line"] == "Original 123 Street"


def test_order_cancellation_after_all_shipments_cancelled_restores_inventory_once(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-shipment-inventory")
    _select_page(session, alice, page)
    customer = _customer(session, page, "inventory")
    product = Product(
        facebook_page_id=page.id,
        name="Tracked Shipment Product",
        sku="TRACK-SHIP",
        currency="VND",
        sale_price=Decimal("10"),
        is_active=True,
        track_inventory=True,
    )
    session.add(product)
    session.commit()
    opened = client.post(
        f"/api/v1/facebook/products/{product.public_id}/inventory/enable",
        headers=_auth(alice),
        json={"opening_quantity": 5, "note": "Opening"},
    )
    assert opened.status_code == 200
    order = _create_confirmed_order(client, alice, customer, product_uuid=str(product.public_id))
    assert session.query(ProductInventory).one().quantity_on_hand == 3
    shipment = _create_shipment(client, alice, order["uuid"])
    _patch_shipment(client, alice, shipment["uuid"], "packed")
    _patch_shipment(client, alice, shipment["uuid"], "cancelled")
    assert session.query(ProductInventory).one().quantity_on_hand == 3
    assert session.query(StockMovement).filter_by(movement_type="ORDER_CANCEL_RESTORE").count() == 0

    cancelled_order = client.patch(
        f"/api/v1/facebook/orders/{order['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert cancelled_order.status_code == 200
    assert session.query(ProductInventory).one().quantity_on_hand == 5
    assert session.query(StockMovement).filter_by(movement_type="ORDER_CANCEL_RESTORE").count() == 1
    repeat = client.patch(
        f"/api/v1/facebook/orders/{order['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert repeat.status_code == 200
    assert session.query(ProductInventory).one().quantity_on_hand == 5
    assert session.query(StockMovement).filter_by(movement_type="ORDER_CANCEL_RESTORE").count() == 1


def test_timeline_includes_shipment_events_and_keeps_query_count_constant(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-shipment-timeline")
    _select_page(session, alice, page)
    customer = _customer(session, page, "timeline")
    order = _create_confirmed_order(client, alice, customer)
    shipment = _create_shipment(client, alice, order["uuid"])
    _patch_shipment(client, alice, shipment["uuid"], "packed")

    response = client.get(
        f"/api/v1/facebook/orders/{order['uuid']}/timeline",
        headers=_auth(alice),
    )
    assert response.status_code == 200
    shipment_items = [
        item for item in response.json()["items"] if item["kind"] == "shipment_event"
    ]
    assert [(item["shipment_number"], item["event_type"]) for item in shipment_items] == [
        (shipment["shipment_number"], "CREATED"),
        (shipment["shipment_number"], "PACKED"),
    ]
    assert "shipment_id" not in shipment_items[0]

    statement_count = 0

    def count_statement(*_args: object, **_kwargs: object) -> None:
        nonlocal statement_count
        statement_count += 1

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", count_statement)
    try:
        timeline = get_order_timeline(session, alice, order["uuid"])
    finally:
        event.remove(bind, "before_cursor_execute", count_statement)

    assert timeline is not None
    assert statement_count == 6


def test_manual_shipping_status_still_works_without_shipments(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "page-shipment-manual-before")
    _select_page(session, alice, page)
    customer = _customer(session, page, "manual-before")
    order = _create_confirmed_order(client, alice, customer)

    response = client.patch(
        f"/api/v1/facebook/orders/{order['uuid']}",
        headers=_auth(alice),
        json={"shipping_status": "packed"},
    )

    assert response.status_code == 200
    assert response.json()["shipping_status"] == "packed"
