"""Tests for customer-centric order backend foundation."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

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
from app.models.orders import Order, OrderEvent, OrderItem
from app.models.products import Product
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.inventory import inventory_reconciles
from app.services.facebook.orders import (
    build_order_create_fingerprint,
    get_order_operational_summary,
    get_order_timeline,
    list_orders,
)
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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


def _make_product(
    db: Session,
    page: FacebookPage,
    *,
    name: str,
    tracked: bool = False,
    active: bool = True,
) -> Product:
    product = Product(
        facebook_page_id=page.id,
        name=name,
        sku=f"SKU-{name}",
        currency="VND",
        sale_price=Decimal("10.00"),
        is_active=active,
        track_inventory=tracked,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def _enable_inventory(
    client: TestClient, user: User, product: Product, quantity: int
) -> dict:
    response = client.post(
        f"/api/v1/facebook/products/{product.public_id}/inventory/enable",
        headers=_auth(user),
        json={"opening_quantity": quantity, "note": "Order integration opening"},
    )
    assert response.status_code == 200
    return response.json()


def _order_customer(db: Session, page: FacebookPage, suffix: str) -> Customer:
    customer = _make_customer(db, name=f"Inventory Buyer {suffix}")
    _make_conversation(
        db,
        page,
        psid=f"psid-inventory-order-{suffix}",
        customer_id=customer.id,
    )
    return customer


def _idempotency_headers(user: User, key: str) -> dict[str, str]:
    return {**_auth(user), "Idempotency-Key": key}


def _seed_operational_queue_orders(
    session: Session,
    page: FacebookPage,
    user: User,
    customer: Customer,
) -> dict[str, str]:
    definitions = [
        ("draft", "draft", "unpaid", "pending"),
        ("unpaid-pending", "confirmed", "unpaid", "pending"),
        ("partial-pending", "confirmed", "partial", "pending"),
        ("paid-pending", "confirmed", "paid", "pending"),
        ("paid-packed", "confirmed", "paid", "packed"),
        ("unpaid-packed", "confirmed", "unpaid", "packed"),
        ("paid-shipped", "confirmed", "paid", "shipped"),
        ("refunded-shipped", "confirmed", "refunded", "shipped"),
        ("paid-delivered", "confirmed", "paid", "delivered"),
        ("shipping-cancelled", "confirmed", "paid", "cancelled"),
        ("order-cancelled", "cancelled", "unpaid", "pending"),
    ]
    result: dict[str, str] = {}
    now = datetime.now(UTC)
    for index, (label, order_status, payment_status, shipping_status) in enumerate(definitions):
        order = Order(
            facebook_page_id=page.id,
            customer_id=customer.id,
            order_number=f"ORD-QUEUE-{label.upper()}",
            status=order_status,
            payment_status=payment_status,
            shipping_status=shipping_status,
            customer_name_snapshot=customer.name,
            created_by_id=user.id,
            created_at=now + timedelta(seconds=index),
            cancelled_at=now + timedelta(seconds=index) if order_status == "cancelled" else None,
        )
        session.add(order)
        session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                item_name=f"Queue item {label}",
                quantity=1,
                unit_price=Decimal("1"),
                line_total=Decimal("1"),
            )
        )
        result[label] = str(order.public_id)
    session.commit()
    return result


def test_order_creation_exact_retry_replays_one_draft_and_conflicts_on_change(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-idempotency-basic")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "idempotency-basic")
    key = str(uuid4())
    payload = _order_payload(str(customer.public_id))

    first = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key.upper()),
        json=payload,
    )
    replay = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, f"  {key}  "),
        json=payload,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["uuid"] == replay.json()["uuid"]
    assert first.json()["order_number"] == replay.json()["order_number"]
    assert session.query(Order).count() == 1
    assert session.query(OrderItem).count() == len(payload["items"])
    assert session.query(OrderEvent).filter_by(event_type="ORDER_CREATED").count() == 1
    stored = session.query(Order).one()
    assert stored.idempotency_key == key
    assert len(stored.request_fingerprint or "") == 64

    changed_payload = {**payload, "items": [{**payload["items"][0], "quantity": 3}]}
    conflict = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=changed_payload,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "Idempotency key was already used for a different order request."
    )
    assert session.query(Order).count() == 1
    assert session.query(OrderItem).count() == len(payload["items"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "cancelled", "status cannot be cancelled when creating an order"),
        ("shipping_status", "packed", "shipping_status must be pending when creating an order"),
    ],
)
def test_order_creation_rejects_impossible_initial_fulfillment_state(
    client: TestClient,
    session: Session,
    field: str,
    value: str,
    message: str,
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, f"page-order-invalid-initial-{field}")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, f"invalid-initial-{field}")
    payload = {**_order_payload(str(customer.public_id)), field: value}

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=payload,
    )

    assert response.status_code == 422
    assert message in str(response.json()["detail"])
    assert session.query(Order).count() == 0


def test_generic_order_patch_rejects_shipping_address_without_mutating_destination(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-generic-shipping-patch")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "generic-shipping-patch")
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json=_order_payload(str(customer.public_id)),
    )
    assert created.status_code == 200
    order_uuid = created.json()["uuid"]

    response = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={"shipping_address": "Mutated outside structured endpoint"},
    )

    assert response.status_code == 422
    session.expire_all()
    order = session.query(Order).filter(Order.public_id == UUID(order_uuid)).one()
    assert order.shipping_address == "123 Test Street"


def test_order_creation_rejects_malformed_idempotency_key(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-idempotency-malformed")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "idempotency-malformed")

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, "not-a-uuid"),
        json=_order_payload(str(customer.public_id)),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Idempotency-Key must be a valid UUID"
    assert session.query(Order).count() == 0


def test_order_creation_idempotency_header_is_allowed_by_cors(client: TestClient) -> None:
    response = client.options(
        "/api/v1/facebook/orders",
        headers={
            "Origin": f"chrome-extension://{'a' * 32}",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )

    assert response.status_code == 200
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in allowed_headers


def test_order_fingerprint_normalizes_defaults_decimals_nulls_and_uuid_case() -> None:
    customer_uuid = uuid4()
    product_uuid = uuid4()
    base = {
        "customer_uuid": str(customer_uuid),
        "conversation_uuid": None,
        "items": [
            {
                "product_uuid": str(product_uuid),
                "quantity": 2,
                "unit_price": Decimal("30000"),
                "note": None,
            }
        ],
    }
    explicit_equivalent = {
        **base,
        "customer_uuid": str(customer_uuid).upper(),
        "items": [
            {
                "product_uuid": str(product_uuid).upper(),
                "item_name": "ignored product snapshot",
                "sku": "ignored-product-sku",
                "quantity": 2,
                "unit_price": Decimal("30000.00"),
                "note": "   ",
            }
        ],
        "status": "DRAFT",
        "payment_status": "UNPAID",
        "shipping_status": "PENDING",
        "currency": " vnd ",
        "discount_amount": Decimal("0.00"),
        "shipping_fee": Decimal("0.0"),
        "shipping_address": "",
        "note": None,
    }

    assert build_order_create_fingerprint(**base) == build_order_create_fingerprint(
        **explicit_equivalent
    )
    reordered = {
        **base,
        "items": [
            base["items"][0],
            {"item_name": "Manual", "quantity": 1, "unit_price": Decimal("1")},
        ],
    }
    reversed_items = {**reordered, "items": list(reversed(reordered["items"]))}
    assert build_order_create_fingerprint(**reordered) != build_order_create_fingerprint(
        **reversed_items
    )


def test_order_creation_key_is_independent_across_pages_and_users(
    client: TestClient, session: Session
) -> None:
    alice, bob = _get_users(session)
    first_page = _make_page(session, alice, "page-order-idempotency-scope-a")
    _select_page(session, alice, first_page)
    first_customer = _order_customer(session, first_page, "scope-a")
    key = str(uuid4())
    first = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=_order_payload(str(first_customer.public_id)),
    )
    assert first.status_code == 200

    second_page = _make_page(session, alice, "page-order-idempotency-scope-b")
    _select_page(session, alice, second_page)
    second_customer = _order_customer(session, second_page, "scope-b")
    second = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=_order_payload(str(second_customer.public_id)),
    )
    assert second.status_code == 200
    assert second.json()["uuid"] != first.json()["uuid"]

    second_page.facebook_account.user_id = bob.id
    session.commit()
    _select_page(session, bob, second_page)
    third = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(bob, key),
        json=_order_payload(str(second_customer.public_id)),
    )
    assert third.status_code == 200
    assert third.json()["uuid"] not in {first.json()["uuid"], second.json()["uuid"]}
    assert session.query(Order).count() == 3


def test_confirmed_order_idempotency_replay_consumes_inventory_once(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-idempotency-confirmed")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "idempotency-confirmed")
    product = _make_product(session, page, name="Idempotent Confirmed")
    _enable_inventory(client, alice, product, 10)
    key = str(uuid4())
    payload = {
        "customer_uuid": str(customer.public_id),
        "status": "confirmed",
        "items": [{"product_uuid": str(product.public_id), "quantity": 3}],
    }

    first = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=payload,
    )
    replay = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=payload,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["uuid"] == replay.json()["uuid"]
    assert session.query(Order).count() == 1
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 1
    assert [
        event.event_type
        for event in session.query(OrderEvent).order_by(OrderEvent.id).all()
    ] == ["ORDER_CREATED", "ORDER_CONFIRMED"]
    inventory = session.query(ProductInventory).filter_by(product_id=product.id).one()
    assert inventory.quantity_on_hand == 7
    assert inventory_reconciles(session, inventory)

    changed = {
        **payload,
        "items": [{"product_uuid": str(product.public_id), "quantity": 4}],
    }
    conflict = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=changed,
    )
    assert conflict.status_code == 409
    session.refresh(inventory)
    assert inventory.quantity_on_hand == 7
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 1


def test_mixed_manual_and_untracked_order_replays_one_item_set(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-idempotency-mixed")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "idempotency-mixed")
    untracked = _make_product(session, page, name="Idempotent Untracked")
    key = str(uuid4())
    payload = {
        "customer_uuid": str(customer.public_id),
        "items": [
            {"product_uuid": str(untracked.public_id), "quantity": 2},
            {"item_name": "Manual", "quantity": 1, "unit_price": 4},
        ],
    }

    first = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=payload,
    )
    replay = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=payload,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["uuid"] == replay.json()["uuid"]
    assert session.query(Order).count() == 1
    assert session.query(OrderItem).count() == 2
    assert session.query(StockMovement).count() == 0


def test_failed_stock_request_does_not_consume_creation_key(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-idempotency-stock-retry")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "idempotency-stock-retry")
    product = _make_product(session, page, name="Idempotent Stock Retry")
    _enable_inventory(client, alice, product, 2)
    key = str(uuid4())
    payload = {
        "customer_uuid": str(customer.public_id),
        "status": "confirmed",
        "items": [{"product_uuid": str(product.public_id), "quantity": 3}],
    }

    failed = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=payload,
    )
    assert failed.status_code == 409
    assert session.query(Order).count() == 0
    assert session.query(OrderEvent).count() == 0

    adjusted = client.post(
        f"/api/v1/facebook/products/{product.public_id}/inventory/adjustments",
        headers=_auth(alice),
        json={"quantity_delta": 3, "note": "Restock", "idempotency_key": str(uuid4())},
    )
    assert adjusted.status_code == 200
    retried = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=payload,
    )
    assert retried.status_code == 200
    assert session.query(Order).count() == 1
    assert session.query(ProductInventory).one().quantity_on_hand == 2


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


def test_shipping_destination_create_detail_and_customer_snapshot_independence(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-shipping-destination")
    _select_page(session, alice, page)
    customer = _make_customer(
        session,
        name="Original Recipient",
        phone="090 123 4567",
        default_address="Legacy customer address",
    )
    _make_conversation(
        session,
        page,
        psid="psid-shipping-destination",
        customer_id=customer.id,
    )
    payload = {
        "customer_uuid": str(customer.public_id),
        "items": [{"item_name": "Parcel", "quantity": 1, "unit_price": 10}],
        "shipping_destination": {
            "recipient_name": "  Nguyễn Văn An  ",
            "recipient_phone": " 090 123 4567 ",
            "address_line": "  12 Đường Hoa Mai  ",
            "ward": " Phường Bến Nghé ",
            "district": " Quận 1 ",
            "province": " Thành phố Hồ Chí Minh ",
            "postal_code": " 700000 ",
            "country_code": " vn ",
            "note": " Gọi trước khi giao ",
        },
    }

    created = client.post("/api/v1/facebook/orders", headers=_auth(alice), json=payload)

    assert created.status_code == 200
    destination = created.json()["shipping_destination"]
    assert destination == {
        "recipient_name": "Nguyễn Văn An",
        "recipient_phone": "090 123 4567",
        "address_line": "12 Đường Hoa Mai",
        "ward": "Phường Bến Nghé",
        "district": "Quận 1",
        "province": "Thành phố Hồ Chí Minh",
        "postal_code": "700000",
        "country_code": "VN",
        "note": "Gọi trước khi giao",
        "is_complete": True,
    }
    order = session.query(Order).filter_by(public_id=UUID(created.json()["uuid"])).one()
    assert order.shipping_recipient_phone_normalized == "+84901234567"

    customer.name = "Changed Customer"
    customer.phone = "0987654321"
    customer.default_address = "Changed customer address"
    session.commit()
    detail = client.get(
        f"/api/v1/facebook/orders/{created.json()['uuid']}",
        headers=_auth(alice),
    )
    assert detail.status_code == 200
    assert detail.json()["shipping_destination"] == destination


def test_shipping_destination_absent_and_partial_orders_remain_valid(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-shipping-partial")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Fallback Recipient", phone="0901111222")
    _make_conversation(session, page, psid="psid-shipping-partial", customer_id=customer.id)
    base = {
        "customer_uuid": str(customer.public_id),
        "items": [{"item_name": "Parcel", "quantity": 1, "unit_price": 10}],
    }

    absent = client.post("/api/v1/facebook/orders", headers=_auth(alice), json=base)
    partial = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={**base, "shipping_destination": {"province": " Hà Nội "}},
    )
    explicitly_empty = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={**base, "shipping_destination": {}},
    )

    assert absent.status_code == 200
    assert absent.json()["shipping_destination"]["recipient_name"] == "Fallback Recipient"
    assert absent.json()["shipping_destination"]["is_complete"] is False
    assert partial.status_code == 200
    assert partial.json()["shipping_destination"] == {
        "recipient_name": None,
        "recipient_phone": None,
        "address_line": None,
        "ward": None,
        "district": None,
        "province": "Hà Nội",
        "postal_code": None,
        "country_code": "VN",
        "note": None,
        "is_complete": False,
    }
    assert explicitly_empty.status_code == 200
    assert explicitly_empty.json()["shipping_destination"] is None


@pytest.mark.parametrize(
    "shipping_destination",
    [
        {"recipient_phone": "not-a-phone"},
        {"country_code": "V1", "province": "Hà Nội"},
    ],
)
def test_shipping_destination_rejects_invalid_phone_and_country(
    client: TestClient,
    session: Session,
    shipping_destination: dict[str, str],
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, f"page-shipping-validation-{uuid4()}")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, f"shipping-validation-{uuid4()}")

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"item_name": "Parcel", "quantity": 1, "unit_price": 10}],
            "shipping_destination": shipping_destination,
        },
    )

    assert response.status_code == 422
    assert session.query(Order).count() == 0


def test_shipping_destination_is_part_of_create_idempotency_fingerprint(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-shipping-idempotency")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "shipping-idempotency")
    key = str(uuid4())
    payload = {
        "customer_uuid": str(customer.public_id),
        "items": [{"item_name": "Parcel", "quantity": 1, "unit_price": 10}],
        "shipping_destination": {
            "recipient_name": "Recipient",
            "recipient_phone": "0901234567",
            "address_line": "10 First Street",
            "ward": "Ward 1",
            "district": "District 1",
            "province": "Hồ Chí Minh",
        },
    }

    first = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json=payload,
    )
    equivalent = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json={
            **payload,
            "shipping_destination": {
                **payload["shipping_destination"],
                "recipient_name": " Recipient ",
                "recipient_phone": "090 123 4567",
                "country_code": "vn",
            },
        },
    )
    changed = client.post(
        "/api/v1/facebook/orders",
        headers=_idempotency_headers(alice, key),
        json={
            **payload,
            "shipping_destination": {
                **payload["shipping_destination"],
                "address_line": "11 Changed Street",
            },
        },
    )

    assert first.status_code == equivalent.status_code == 200
    assert first.json()["uuid"] == equivalent.json()["uuid"]
    assert changed.status_code == 409
    assert session.query(Order).count() == 1


def test_shipping_destination_update_is_page_safe_repeatable_and_stock_neutral(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page_a = _make_page(session, alice, "page-shipping-update-a")
    page_b = _make_page(session, alice, "page-shipping-update-b")
    _select_page(session, alice, page_a)
    customer = _order_customer(session, page_a, "shipping-update")
    product = _make_product(session, page_a, name="Shipping Neutral", tracked=True)
    _enable_inventory(client, alice, product, 5)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "payment_status": "partial",
            "shipping_status": "pending",
            "items": [{"product_uuid": str(product.public_id), "quantity": 2}],
        },
    )
    assert created.status_code == 200
    order_uuid = created.json()["uuid"]
    packed = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}",
        headers=_auth(alice),
        json={"shipping_status": "packed"},
    )
    assert packed.status_code == 200
    update_payload = {
        "recipient_name": "Packed Recipient",
        "recipient_phone": "0912345678",
        "address_line": "20 Packed Street",
        "ward": "Ward 2",
        "district": "District 2",
        "province": "Đà Nẵng",
    }
    before_events = session.query(OrderEvent).count()
    before_updated_at = created.json()["updated_at"]

    updated = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}/shipping-address",
        headers=_auth(alice),
        json=update_payload,
    )
    same_value = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}/shipping-address",
        headers=_auth(alice),
        json=update_payload,
    )

    assert updated.status_code == same_value.status_code == 200
    assert updated.json()["status"] == "confirmed"
    assert updated.json()["payment_status"] == "partial"
    assert updated.json()["shipping_status"] == "packed"
    assert same_value.json()["updated_at"] == updated.json()["updated_at"]
    assert updated.json()["updated_at"] != before_updated_at
    assert session.query(OrderEvent).count() == before_events
    assert session.query(ProductInventory).one().quantity_on_hand == 3
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 1

    _select_page(session, alice, page_b)
    cross_page = client.patch(
        f"/api/v1/facebook/orders/{order_uuid}/shipping-address",
        headers=_auth(alice),
        json={**update_payload, "address_line": "Leaked"},
    )
    assert cross_page.status_code == 404


@pytest.mark.parametrize(
    ("order_status", "shipping_status"),
    [
        ("cancelled", "pending"),
        ("confirmed", "shipped"),
        ("confirmed", "delivered"),
        ("confirmed", "cancelled"),
    ],
)
def test_shipping_destination_update_is_blocked_after_dispatch_or_cancellation(
    client: TestClient,
    session: Session,
    order_status: str,
    shipping_status: str,
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, f"page-shipping-locked-{order_status}-{shipping_status}")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, f"shipping-locked-{order_status}-{shipping_status}")
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"item_name": "Parcel", "quantity": 1, "unit_price": 10}],
        },
    )
    order = session.query(Order).filter_by(public_id=UUID(created.json()["uuid"])).one()
    order.status = order_status
    order.shipping_status = shipping_status
    session.commit()

    response = client.patch(
        f"/api/v1/facebook/orders/{order.public_id}/shipping-address",
        headers=_auth(alice),
        json={"address_line": "Blocked change"},
    )

    assert response.status_code == 409
    session.refresh(order)
    assert order.shipping_address is None


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


def test_order_workspace_filters_search_and_page_scope(
    client: TestClient, session: Session
) -> None:
    alice, bob = _get_users(session)
    page = _make_page(session, alice, "page-order-workspace")
    other_page = _make_page(session, bob, "page-order-workspace-other")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Workspace Buyer")
    other_customer = _make_customer(session, name="Foreign Workspace Buyer")
    _make_conversation(session, page, psid="psid-order-workspace", customer_id=customer.id)
    _make_conversation(
        session,
        other_page,
        psid="psid-order-workspace-other",
        customer_id=other_customer.id,
    )

    draft = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "payment_status": "unpaid",
            "shipping_status": "pending",
            "items": [{"item_name": "Draft item", "quantity": 1, "unit_price": 10}],
        },
    )
    confirmed = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "payment_status": "paid",
            "shipping_status": "pending",
            "items": [{"item_name": "Confirmed item", "quantity": 2, "unit_price": 20}],
        },
    )
    assert draft.status_code == confirmed.status_code == 200
    confirmed = client.patch(
        f"/api/v1/facebook/orders/{confirmed.json()['uuid']}",
        headers=_auth(alice),
        json={"shipping_status": "packed"},
    )
    assert confirmed.status_code == 200

    _select_page(session, bob, other_page)
    foreign = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(bob),
        json={
            "customer_uuid": str(other_customer.public_id),
            "status": "confirmed",
            "payment_status": "paid",
            "shipping_status": "pending",
            "items": [{"item_name": "Foreign item", "quantity": 1, "unit_price": 99}],
        },
    )
    assert foreign.status_code == 200
    foreign = client.patch(
        f"/api/v1/facebook/orders/{foreign.json()['uuid']}",
        headers=_auth(bob),
        json={"shipping_status": "packed"},
    )
    assert foreign.status_code == 200
    _select_page(session, alice, page)

    combined = client.get(
        "/api/v1/facebook/orders?status=confirmed&payment_status=paid&shipping_status=packed",
        headers=_auth(alice),
    )
    assert combined.status_code == 200
    assert combined.json()["meta"]["total"] == 1
    assert combined.json()["items"][0]["uuid"] == confirmed.json()["uuid"]
    assert combined.json()["items"][0]["item_count"] == 1
    assert combined.json()["items"][0]["total_amount"] == "40.00"
    assert combined.json()["items"][0]["customer_name"] == "Workspace Buyer"

    by_order_number = client.get(
        f"/api/v1/facebook/orders?q={confirmed.json()['order_number'][4:12]}",
        headers=_auth(alice),
    )
    assert by_order_number.status_code == 200
    assert by_order_number.json()["meta"]["total"] >= 1
    assert foreign.json()["uuid"] not in {
        item["uuid"] for item in by_order_number.json()["items"]
    }

    by_customer = client.get(
        "/api/v1/facebook/orders?q=Workspace%20Buyer&page=1&page_size=1",
        headers=_auth(alice),
    )
    assert by_customer.status_code == 200
    assert by_customer.json()["meta"]["total"] == 2
    assert len(by_customer.json()["items"]) == 1


def test_operational_queue_semantics_filters_pagination_and_page_scope(
    client: TestClient,
    session: Session,
) -> None:
    alice, bob = _get_users(session)
    page = _make_page(session, alice, "page-operational-queues")
    other_page = _make_page(session, bob, "page-operational-queues-other")
    customer = _make_customer(session, name="Operational Queue Buyer")
    other_customer = _make_customer(session, name="Foreign Queue Buyer")
    _make_conversation(session, page, psid="psid-operational-queues", customer_id=customer.id)
    _make_conversation(
        session,
        other_page,
        psid="psid-operational-queues-other",
        customer_id=other_customer.id,
    )
    _select_page(session, alice, page)
    orders = _seed_operational_queue_orders(session, page, alice, customer)
    _select_page(session, bob, other_page)
    foreign = _seed_operational_queue_orders(session, other_page, bob, other_customer)
    _select_page(session, alice, page)

    expected = {
        "draft": {orders["draft"]},
        "needs_payment": {
            orders["unpaid-pending"],
            orders["partial-pending"],
            orders["unpaid-packed"],
        },
        "needs_packing": {
            orders["unpaid-pending"],
            orders["partial-pending"],
            orders["paid-pending"],
        },
        "packed": {orders["paid-packed"], orders["unpaid-packed"]},
        "in_transit": {orders["paid-shipped"], orders["refunded-shipped"]},
        "shipping_issue": {orders["shipping-cancelled"]},
        "cancelled": {orders["order-cancelled"]},
    }
    for queue, expected_uuids in expected.items():
        response = client.get(f"/api/v1/facebook/orders?queue={queue}", headers=_auth(alice))
        assert response.status_code == 200
        assert response.json()["meta"]["total"] == len(expected_uuids)
        assert {item["uuid"] for item in response.json()["items"]} == expected_uuids
        assert not set(foreign.values()).intersection(expected_uuids)

    searched = client.get(
        "/api/v1/facebook/orders?queue=needs_payment&q=UNPAID-PACKED",
        headers=_auth(alice),
    )
    assert searched.status_code == 200
    assert [item["uuid"] for item in searched.json()["items"]] == [orders["unpaid-packed"]]

    combined = client.get(
        "/api/v1/facebook/orders?queue=needs_payment&shipping_status=packed",
        headers=_auth(alice),
    )
    assert combined.status_code == 200
    assert [item["uuid"] for item in combined.json()["items"]] == [orders["unpaid-packed"]]

    contradictory = client.get(
        "/api/v1/facebook/orders?queue=packed&shipping_status=pending",
        headers=_auth(alice),
    )
    assert contradictory.status_code == 200
    assert contradictory.json()["meta"]["total"] == 0

    paginated = client.get(
        "/api/v1/facebook/orders?queue=needs_packing&page=2&page_size=2",
        headers=_auth(alice),
    )
    assert paginated.status_code == 200
    assert paginated.json()["meta"]["total"] == 3
    assert len(paginated.json()["items"]) == 1

    invalid = client.get("/api/v1/facebook/orders?queue=unknown", headers=_auth(alice))
    assert invalid.status_code == 422


def test_operational_summary_counts_overlap_and_follow_lifecycle(
    client: TestClient,
    session: Session,
) -> None:
    alice, bob = _get_users(session)
    page = _make_page(session, alice, "page-operational-summary")
    other_page = _make_page(session, bob, "page-operational-summary-other")
    customer = _make_customer(session, name="Operational Summary Buyer")
    other_customer = _make_customer(session, name="Foreign Summary Buyer")
    _make_conversation(session, page, psid="psid-operational-summary", customer_id=customer.id)
    _make_conversation(
        session,
        other_page,
        psid="psid-operational-summary-other",
        customer_id=other_customer.id,
    )
    _select_page(session, alice, page)
    _seed_operational_queue_orders(session, page, alice, customer)
    _select_page(session, bob, other_page)
    _seed_operational_queue_orders(session, other_page, bob, other_customer)
    _select_page(session, alice, page)

    response = client.get("/api/v1/facebook/orders/operational-summary", headers=_auth(alice))
    assert response.status_code == 200
    assert response.json() == {
        "all": 11,
        "draft": 1,
        "needs_payment": 3,
        "needs_packing": 3,
        "packed": 2,
        "in_transit": 2,
        "shipping_issue": 1,
        "cancelled": 1,
    }

    transition = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"item_name": "Transition item", "quantity": 1, "unit_price": 1}],
        },
    )
    assert transition.status_code == 200
    order_uuid = transition.json()["uuid"]

    after_create = client.get(
        "/api/v1/facebook/orders/operational-summary", headers=_auth(alice)
    ).json()
    assert after_create["all"] == 12
    assert after_create["draft"] == 2

    for payload, entered, left in [
        ({"status": "confirmed"}, ("needs_payment", "needs_packing"), ("draft",)),
        (
            {"payment_status": "paid", "shipping_status": "packed"},
            ("packed",),
            ("needs_payment", "needs_packing"),
        ),
        ({"shipping_status": "shipped"}, ("in_transit",), ("packed",)),
        ({"shipping_status": "cancelled"}, ("shipping_issue",), ("in_transit",)),
        ({"status": "cancelled"}, ("cancelled",), ("shipping_issue",)),
    ]:
        before = client.get(
            "/api/v1/facebook/orders/operational-summary", headers=_auth(alice)
        ).json()
        updated = client.patch(
            f"/api/v1/facebook/orders/{order_uuid}",
            headers=_auth(alice),
            json=payload,
        )
        assert updated.status_code == 200
        after = client.get(
            "/api/v1/facebook/orders/operational-summary", headers=_auth(alice)
        ).json()
        for queue in entered:
            assert after[queue] == before[queue] + 1
        for queue in left:
            assert after[queue] == before[queue] - 1

    assert session.query(StockMovement).count() == 0


def test_order_workspace_list_has_constant_query_count(session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-workspace-query-count")
    _select_page(session, alice, page)
    customer = _make_customer(session, name="Query Count Buyer")
    _make_conversation(
        session,
        page,
        psid="psid-order-workspace-query-count",
        customer_id=customer.id,
    )
    for index in range(3):
        order = Order(
            facebook_page_id=page.id,
            customer_id=customer.id,
            order_number=f"ORD-QUERY-{index}",
            customer_name_snapshot=customer.name,
            created_by_id=alice.id,
        )
        session.add(order)
        session.flush()
        session.add_all(
            [
                OrderItem(
                    order_id=order.id,
                    item_name=f"Item {item_index}",
                    quantity=1,
                    unit_price=Decimal("1"),
                    line_total=Decimal("1"),
                )
                for item_index in range(index + 1)
            ]
        )
    session.commit()

    audit_session = Session(bind=session.get_bind())
    audit_user = audit_session.get(User, alice.id)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", capture_statement)
    try:
        result = list_orders(audit_session, audit_user, page=1, page_size=20)
        assert result is not None
        assert [record.item_count for record in result.items] == [3, 2, 1]
        assert all(record.customer_name == "Query Count Buyer" for record in result.items)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", capture_statement)

    assert len(statements) == 4

    statements.clear()
    event.listen(session.get_bind(), "before_cursor_execute", capture_statement)
    try:
        summary = get_order_operational_summary(audit_session, audit_user)
        assert summary is not None
        assert summary.all == 3
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", capture_statement)
        audit_session.close()

    assert len(statements) == 3


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

    for query in ("payment_status=unknown", "shipping_status=unknown"):
        response = client.get(f"/api/v1/facebook/orders?{query}", headers=_auth(alice))
        assert response.status_code == 422


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
    assert history.json()["items"][0]["customer_uuid"] == str(primary.public_id)
    assert history.json()["items"][0]["customer_name"] == primary.name

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


def test_draft_order_has_no_stock_effect_for_tracked_untracked_or_manual_items(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-draft")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "draft")
    tracked = _make_product(session, page, name="Draft Tracked")
    untracked = _make_product(session, page, name="Draft Untracked")
    _enable_inventory(client, alice, tracked, 10)

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [
                {"product_uuid": str(tracked.public_id), "quantity": 2},
                {"product_uuid": str(untracked.public_id), "quantity": 3},
                {"item_name": "Manual", "quantity": 4, "unit_price": 1},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert session.query(ProductInventory).one().quantity_on_hand == 10
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 0


def test_direct_confirmed_creation_consumes_only_tracked_product(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-direct-confirm")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "direct-confirm")
    tracked = _make_product(session, page, name="Direct Tracked")
    untracked = _make_product(session, page, name="Direct Untracked")
    _enable_inventory(client, alice, tracked, 10)

    response = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [
                {"product_uuid": str(tracked.public_id), "quantity": 2},
                {"product_uuid": str(untracked.public_id), "quantity": 3},
                {"item_name": "Manual", "quantity": 1, "unit_price": 1},
            ],
        },
    )
    assert response.status_code == 200
    order = session.query(Order).filter(Order.public_id == UUID(response.json()["uuid"])).one()
    inventory = session.query(ProductInventory).filter_by(product_id=tracked.id).one()
    movement = session.query(StockMovement).filter_by(movement_type="ORDER_OUT").one()
    assert inventory.quantity_on_hand == 8
    assert movement.order_id == order.id
    assert movement.product_id == tracked.id
    assert movement.quantity_delta == -2
    assert movement.created_by_id == alice.id
    assert inventory_reconciles(session, inventory)


def test_confirm_same_product_rows_sequences_movements_and_retries_once(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-same-product")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "same-product")
    product = _make_product(session, page, name="Repeated Product")
    _enable_inventory(client, alice, product, 10)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [
                {"product_uuid": str(product.public_id), "quantity": 2},
                {"product_uuid": str(product.public_id), "quantity": 3},
            ],
        },
    ).json()

    confirmed = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    assert confirmed.status_code == 200
    movements = (
        session.query(StockMovement)
        .filter_by(movement_type="ORDER_OUT")
        .order_by(StockMovement.order_item_id)
        .all()
    )
    assert [(m.quantity_before, m.quantity_after, m.quantity_delta) for m in movements] == [
        (10, 8, -2),
        (8, 5, -3),
    ]
    assert session.query(ProductInventory).one().quantity_on_hand == 5

    retry = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    assert retry.status_code == 200
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 2
    assert session.query(ProductInventory).one().quantity_on_hand == 5
    rejected = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "draft"},
    )
    assert rejected.status_code == 422
    assert "confirmed to draft" in rejected.json()["detail"]


def test_cancel_restores_actual_out_after_disable_and_archive_exactly_once(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-cancel")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "cancel")
    product = _make_product(session, page, name="Cancel Product")
    _enable_inventory(client, alice, product, 10)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [{"product_uuid": str(product.public_id), "quantity": 3}],
        },
    ).json()
    assert session.query(ProductInventory).one().quantity_on_hand == 7
    client.post(
        f"/api/v1/facebook/products/{product.public_id}/inventory/disable", headers=_auth(alice)
    )
    client.delete(f"/api/v1/facebook/products/{product.public_id}", headers=_auth(alice))

    cancelled = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200
    restore = session.query(StockMovement).filter_by(movement_type="ORDER_CANCEL_RESTORE").one()
    out = session.query(StockMovement).filter_by(movement_type="ORDER_OUT").one()
    assert restore.quantity_delta == abs(out.quantity_delta) == 3
    assert restore.quantity_before == 7
    assert restore.quantity_after == 10
    assert session.query(ProductInventory).one().quantity_on_hand == 10

    retry = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert retry.status_code == 200
    assert (
        session.query(StockMovement).filter_by(movement_type="ORDER_CANCEL_RESTORE").count()
        == 1
    )
    for status_value in ("confirmed", "draft"):
        rejected = client.patch(
            f"/api/v1/facebook/orders/{created['uuid']}",
            headers=_auth(alice),
            json={"status": status_value},
        )
        assert rejected.status_code == 422


def test_draft_cancel_has_no_stock_effect(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-draft-cancel")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "draft-cancel")
    product = _make_product(session, page, name="Draft Cancel Product")
    _enable_inventory(client, alice, product, 4)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"product_uuid": str(product.public_id), "quantity": 2}],
        },
    ).json()
    response = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert response.status_code == 200
    assert session.query(ProductInventory).one().quantity_on_hand == 4
    assert session.query(StockMovement).filter(StockMovement.order_id.is_not(None)).count() == 0


def test_insufficient_direct_confirm_rolls_back_order_and_all_patch_fields(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-insufficient")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "insufficient")
    product = _make_product(session, page, name="Low Stock")
    _enable_inventory(client, alice, product, 2)
    order_count = session.query(Order).count()

    direct = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [{"product_uuid": str(product.public_id), "quantity": 3}],
        },
    )
    assert direct.status_code == 409
    assert direct.json()["detail"] == "Insufficient inventory for one or more products"
    assert session.query(Order).count() == order_count
    assert session.query(ProductInventory).one().quantity_on_hand == 2

    draft = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "note": "Original",
            "items": [{"product_uuid": str(product.public_id), "quantity": 3}],
        },
    ).json()
    failed_patch = client.patch(
        f"/api/v1/facebook/orders/{draft['uuid']}",
        headers=_auth(alice),
        json={"status": "confirmed", "payment_status": "paid", "note": "Changed"},
    )
    assert failed_patch.status_code == 409
    stored = session.query(Order).filter(Order.public_id == UUID(draft["uuid"])).one()
    assert stored.status == "draft"
    assert stored.payment_status == "unpaid"
    assert stored.note == "Original"
    assert session.query(ProductInventory).one().quantity_on_hand == 2
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 0
    assert [event.event_type for event in session.query(OrderEvent).all()] == ["ORDER_CREATED"]


def test_confirmation_validates_all_products_before_any_stock_mutation(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-all-or-nothing")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "all-or-nothing")
    enough = _make_product(session, page, name="Enough")
    low = _make_product(session, page, name="Low")
    _enable_inventory(client, alice, enough, 5)
    _enable_inventory(client, alice, low, 1)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [
                {"product_uuid": str(enough.public_id), "quantity": 2},
                {"product_uuid": str(low.public_id), "quantity": 2},
            ],
        },
    ).json()
    response = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    assert response.status_code == 409
    balances = {
        row.product_id: row.quantity_on_hand for row in session.query(ProductInventory).all()
    }
    assert balances == {enough.id: 5, low.id: 1}
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 0


def test_confirmation_uses_current_tracking_and_allows_archived_draft_product(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-tracking-change")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "tracking-change")
    enabled_later = _make_product(session, page, name="Enabled Later")
    disabled_later = _make_product(session, page, name="Disabled Later")
    _enable_inventory(client, alice, disabled_later, 10)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [
                {"product_uuid": str(enabled_later.public_id), "quantity": 2},
                {"product_uuid": str(disabled_later.public_id), "quantity": 3},
            ],
        },
    ).json()
    _enable_inventory(client, alice, enabled_later, 6)
    client.post(
        f"/api/v1/facebook/products/{disabled_later.public_id}/inventory/disable",
        headers=_auth(alice),
    )
    client.delete(
        f"/api/v1/facebook/products/{enabled_later.public_id}", headers=_auth(alice)
    )

    response = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    assert response.status_code == 200
    balances = {
        row.product_id: row.quantity_on_hand for row in session.query(ProductInventory).all()
    }
    assert balances == {enabled_later.id: 4, disabled_later.id: 10}
    outs = session.query(StockMovement).filter_by(movement_type="ORDER_OUT").all()
    assert [movement.product_id for movement in outs] == [enabled_later.id]


def test_historical_confirmed_order_without_out_is_not_consumed_or_restored(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-historical")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "historical")
    product = _make_product(session, page, name="Historical Product")
    _enable_inventory(client, alice, product, 9)
    order = Order(
        facebook_page_id=page.id,
        customer_id=customer.id,
        order_number="ORD-HISTORICAL-STOCK",
        status="confirmed",
        subtotal_amount=Decimal("20"),
        total_amount=Decimal("20"),
    )
    session.add(order)
    session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=product.id,
            item_name=product.name,
            quantity=2,
            unit_price=Decimal("10"),
            line_total=Decimal("20"),
        )
    )
    session.commit()

    same_state = client.patch(
        f"/api/v1/facebook/orders/{order.public_id}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    cancelled = client.patch(
        f"/api/v1/facebook/orders/{order.public_id}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert same_state.status_code == cancelled.status_code == 200
    assert session.query(ProductInventory).one().quantity_on_hand == 9
    assert session.query(StockMovement).filter(StockMovement.order_id.is_not(None)).count() == 0


def test_payment_and_shipping_statuses_never_change_inventory(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-status-neutral")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "status-neutral")
    product = _make_product(session, page, name="Status Neutral")
    _enable_inventory(client, alice, product, 10)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [{"product_uuid": str(product.public_id), "quantity": 2}],
        },
    ).json()
    original_count = session.query(StockMovement).count()
    for payload in (
        {"payment_status": "paid"},
        {"payment_status": "refunded"},
        {"shipping_status": "packed"},
        {"shipping_status": "shipped"},
        {"shipping_status": "delivered"},
        {"shipping_status": "cancelled"},
    ):
        response = client.patch(
            f"/api/v1/facebook/orders/{created['uuid']}",
            headers=_auth(alice),
            json=payload,
        )
        assert response.status_code == 200
    assert session.query(ProductInventory).one().quantity_on_hand == 8
    assert session.query(StockMovement).count() == original_count


def test_tracked_product_without_balance_fails_closed(client: TestClient, session: Session) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-missing-balance")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "missing-balance")
    product = _make_product(session, page, name="Missing Balance", tracked=True)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"product_uuid": str(product.public_id), "quantity": 1}],
        },
    ).json()
    response = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "A tracked Product has no inventory balance"
    stored_order = session.query(Order).filter(Order.public_id == UUID(created["uuid"])).one()
    session.refresh(stored_order)
    assert stored_order.status == "draft"


def test_inconsistent_order_item_product_page_fails_closed(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page_a = _make_page(session, alice, "page-stock-consistency-a")
    page_b = _make_page(session, alice, "page-stock-consistency-b")
    _select_page(session, alice, page_b)
    foreign_product = _make_product(session, page_b, name="Foreign Inventory")
    _enable_inventory(client, alice, foreign_product, 5)
    customer = _order_customer(session, page_a, "page-consistency")
    order = Order(
        facebook_page_id=page_a.id,
        customer_id=customer.id,
        order_number="ORD-INCONSISTENT-PRODUCT-PAGE",
        subtotal_amount=Decimal("10"),
        total_amount=Decimal("10"),
    )
    session.add(order)
    session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=foreign_product.id,
            item_name=foreign_product.name,
            quantity=1,
            unit_price=Decimal("10"),
            line_total=Decimal("10"),
        )
    )
    session.commit()
    _select_page(session, alice, page_a)

    response = client.patch(
        f"/api/v1/facebook/orders/{order.public_id}",
        headers=_auth(alice),
        json={"status": "confirmed"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Order contains a Product outside its Facebook Page"
    assert session.query(ProductInventory).one().quantity_on_hand == 5
    assert session.query(StockMovement).filter_by(movement_type="ORDER_OUT").count() == 0


def test_historical_partial_out_cancellation_restores_only_actual_consumption(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-partial-history")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "partial-history")
    first = _make_product(session, page, name="Partial First")
    second = _make_product(session, page, name="Partial Second")
    _enable_inventory(client, alice, first, 5)
    _enable_inventory(client, alice, second, 5)
    order = Order(
        facebook_page_id=page.id,
        customer_id=customer.id,
        order_number="ORD-PARTIAL-HISTORY",
        status="confirmed",
        subtotal_amount=Decimal("40"),
        total_amount=Decimal("40"),
    )
    session.add(order)
    session.flush()
    first_item = OrderItem(
        order_id=order.id,
        product_id=first.id,
        item_name=first.name,
        quantity=2,
        unit_price=Decimal("10"),
        line_total=Decimal("20"),
    )
    second_item = OrderItem(
        order_id=order.id,
        product_id=second.id,
        item_name=second.name,
        quantity=2,
        unit_price=Decimal("10"),
        line_total=Decimal("20"),
    )
    session.add_all([first_item, second_item])
    session.flush()
    first_inventory = session.query(ProductInventory).filter_by(product_id=first.id).one()
    first_inventory.quantity_on_hand = 3
    session.add(
        StockMovement(
            public_id=uuid4(),
            product_id=first.id,
            order_id=order.id,
            order_item_id=first_item.id,
            movement_type="ORDER_OUT",
            quantity_delta=-2,
            quantity_before=5,
            quantity_after=3,
            idempotency_key=f"ORDER_CONFIRM:{first_item.public_id}",
            created_by_id=alice.id,
        )
    )
    session.commit()

    response = client.patch(
        f"/api/v1/facebook/orders/{order.public_id}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert response.status_code == 200
    balances = {
        row.product_id: row.quantity_on_hand for row in session.query(ProductInventory).all()
    }
    assert balances == {first.id: 5, second.id: 5}
    restores = session.query(StockMovement).filter_by(movement_type="ORDER_CANCEL_RESTORE").all()
    assert len(restores) == 1
    assert restores[0].order_item_id == first_item.id


def test_customer_merge_after_confirm_is_inventory_neutral(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-merge")
    _select_page(session, alice, page)
    primary = _make_customer(session, name="Stock Merge Primary")
    secondary = _make_customer(session, name="Stock Merge Primary")
    primary_conversation = _make_conversation(
        session,
        page,
        psid="psid-stock-merge-primary",
        customer_id=primary.id,
        customer_name="Stock Merge Primary",
        customer_avatar_url="https://img.example.com/stock-merge.png",
    )
    secondary_conversation = _make_conversation(
        session,
        page,
        psid="psid-stock-merge-secondary",
        customer_id=secondary.id,
        customer_name="Stock Merge Primary",
        customer_avatar_url="https://img.example.com/stock-merge.png",
    )
    product = _make_product(session, page, name="Merge Stock")
    _enable_inventory(client, alice, product, 10)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(secondary.public_id),
            "conversation_uuid": str(secondary_conversation.uuid),
            "status": "confirmed",
            "items": [{"product_uuid": str(product.public_id), "quantity": 3}],
        },
    ).json()
    movement = session.query(StockMovement).filter_by(movement_type="ORDER_OUT").one()
    movement_identity = (movement.public_id, movement.order_id, movement.order_item_id)
    event_identities = [
        (event.public_id, event.event_type)
        for event in session.query(OrderEvent).order_by(OrderEvent.id).all()
    ]

    merged = client.post(
        f"/api/v1/facebook/customers/{primary_conversation.uuid}/merge",
        headers=_auth(alice),
        json={"secondary_customer_id": str(secondary_conversation.uuid)},
    )
    assert merged.status_code == 200
    order = session.query(Order).filter(Order.public_id == UUID(created["uuid"])).one()
    session.refresh(order)
    movement = session.query(StockMovement).filter_by(movement_type="ORDER_OUT").one()
    assert order.customer_id == primary.id
    assert session.query(ProductInventory).one().quantity_on_hand == 7
    assert (movement.public_id, movement.order_id, movement.order_item_id) == movement_identity
    assert [
        (event.public_id, event.event_type)
        for event in session.query(OrderEvent).order_by(OrderEvent.id).all()
    ] == event_identities
    timeline = client.get(
        f"/api/v1/facebook/orders/{created['uuid']}/timeline", headers=_auth(alice)
    )
    assert timeline.status_code == 200
    timeline_event_types = [
        item["event_type"]
        for item in timeline.json()["items"]
        if item["kind"] == "order_event"
    ]
    assert timeline_event_types == [
        "ORDER_CREATED",
        "ORDER_CONFIRMED",
    ]
    assert session.query(StockMovement).count() == 2  # OPENING + ORDER_OUT


def test_cancellation_with_missing_balance_fails_without_changing_order(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-stock-cancel-missing-balance")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "cancel-missing-balance")
    product = _make_product(session, page, name="Cancel Missing Balance")
    _enable_inventory(client, alice, product, 5)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [{"product_uuid": str(product.public_id), "quantity": 2}],
        },
    ).json()
    inventory = session.query(ProductInventory).filter_by(product_id=product.id).one()
    session.delete(inventory)
    session.commit()

    response = client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "A tracked Product has no inventory balance"
    order = session.query(Order).filter(Order.public_id == UUID(created["uuid"])).one()
    assert order.status == "confirmed"
    assert session.query(StockMovement).filter_by(movement_type="ORDER_CANCEL_RESTORE").count() == 0
    assert session.query(OrderEvent).filter_by(event_type="ORDER_CANCELLED").count() == 0


def test_order_events_capture_real_transitions_and_suppress_same_state_retries(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-events-transitions")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "events-transitions")
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"item_name": "Manual event item", "quantity": 1, "unit_price": 4}],
        },
    ).json()

    multi = {"status": "confirmed", "payment_status": "partial", "shipping_status": "packed"}
    assert client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}", headers=_auth(alice), json=multi
    ).status_code == 200
    event_count = session.query(OrderEvent).count()
    assert client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}", headers=_auth(alice), json=multi
    ).status_code == 200
    assert session.query(OrderEvent).count() == event_count

    for payment_status in ("paid", "paid", "refunded"):
        assert client.patch(
            f"/api/v1/facebook/orders/{created['uuid']}",
            headers=_auth(alice),
            json={"payment_status": payment_status},
        ).status_code == 200
    for shipping_status in ("shipped", "delivered", "cancelled", "cancelled"):
        assert client.patch(
            f"/api/v1/facebook/orders/{created['uuid']}",
            headers=_auth(alice),
            json={"shipping_status": shipping_status},
        ).status_code == 200
    assert client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    ).status_code == 200
    final_count = session.query(OrderEvent).count()
    assert client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    ).status_code == 200
    assert session.query(OrderEvent).count() == final_count

    events = session.query(OrderEvent).order_by(OrderEvent.id).all()
    assert [event.event_type for event in events] == [
        "ORDER_CREATED",
        "ORDER_CONFIRMED",
        "PAYMENT_STATUS_CHANGED",
        "SHIPPING_STATUS_CHANGED",
        "PAYMENT_STATUS_CHANGED",
        "PAYMENT_STATUS_CHANGED",
        "SHIPPING_STATUS_CHANGED",
        "SHIPPING_STATUS_CHANGED",
        "SHIPPING_STATUS_CHANGED",
        "ORDER_CANCELLED",
    ]
    assert [
        (event.from_value, event.to_value)
        for event in events
        if event.event_type == "PAYMENT_STATUS_CHANGED"
    ] == [("unpaid", "partial"), ("partial", "paid"), ("paid", "refunded")]
    assert [
        (event.from_value, event.to_value)
        for event in events
        if event.event_type == "SHIPPING_STATUS_CHANGED"
    ] == [
        ("pending", "packed"),
        ("packed", "shipped"),
        ("shipped", "delivered"),
        ("delivered", "cancelled"),
    ]
    assert session.query(StockMovement).filter(StockMovement.order_id.is_not(None)).count() == 0


def test_order_timeline_combines_events_and_inventory_using_order_item_snapshots(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-timeline-inventory")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "timeline-inventory")
    product = _make_product(session, page, name="Timeline Original")
    _enable_inventory(client, alice, product, 8)
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "status": "confirmed",
            "items": [{"product_uuid": str(product.public_id), "quantity": 2}],
        },
    ).json()

    product.name = "Timeline Renamed"
    product.sku = "RENAMED-SKU"
    session.commit()
    initial = client.get(
        f"/api/v1/facebook/orders/{created['uuid']}/timeline", headers=_auth(alice)
    )
    assert initial.status_code == 200
    initial_items = initial.json()["items"]
    initial_types = [
        (item["kind"], item.get("event_type") or item.get("movement_type"))
        for item in initial_items
    ]
    assert initial_types == [
        ("order_event", "ORDER_CREATED"),
        ("order_event", "ORDER_CONFIRMED"),
        ("inventory_movement", "ORDER_OUT"),
    ]
    movement = initial_items[2]
    assert movement["product_name"] == "Timeline Original"
    assert movement["sku"] == "SKU-Timeline Original"
    assert movement["quantity_delta"] == -2
    assert movement["quantity_before"] == 8
    assert movement["quantity_after"] == 6
    assert movement["actor"] == {
        "name": "Alice Orders",
        "email": "alice_orders@example.com",
    }
    assert "order_id" not in movement
    assert "order_item_id" not in movement
    assert all(item.get("movement_type") != "OPENING" for item in initial_items)

    assert client.patch(
        f"/api/v1/facebook/orders/{created['uuid']}",
        headers=_auth(alice),
        json={"status": "cancelled"},
    ).status_code == 200
    final_items = client.get(
        f"/api/v1/facebook/orders/{created['uuid']}/timeline", headers=_auth(alice)
    ).json()["items"]
    final_types = [
        (item["kind"], item.get("event_type") or item.get("movement_type"))
        for item in final_items[-2:]
    ]
    assert final_types == [
        ("order_event", "ORDER_CANCELLED"),
        ("inventory_movement", "ORDER_CANCEL_RESTORE"),
    ]
    assert final_items[-1]["product_name"] == "Timeline Original"
    assert final_items[-1]["quantity_delta"] == 2


def test_order_timeline_is_page_scoped_and_supports_historical_empty_history(
    client: TestClient, session: Session
) -> None:
    alice, bob = _get_users(session)
    alice_page = _make_page(session, alice, "page-order-timeline-a")
    bob_page = _make_page(session, bob, "page-order-timeline-b")
    _select_page(session, alice, alice_page)
    customer = _order_customer(session, alice_page, "timeline-historical")
    historical = Order(
        facebook_page_id=alice_page.id,
        customer_id=customer.id,
        order_number="ORD-HISTORICAL-NO-EVENTS",
        status="confirmed",
        payment_status="paid",
        shipping_status="delivered",
        created_by_id=alice.id,
    )
    session.add(historical)
    session.commit()

    response = client.get(
        f"/api/v1/facebook/orders/{historical.public_id}/timeline", headers=_auth(alice)
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}

    _select_page(session, bob, bob_page)
    foreign = client.get(
        f"/api/v1/facebook/orders/{historical.public_id}/timeline", headers=_auth(bob)
    )
    assert foreign.status_code == 404
    assert client.get(
        "/api/v1/facebook/orders/not-a-uuid/timeline", headers=_auth(bob)
    ).status_code == 404


def test_order_timeline_has_constant_query_count(
    client: TestClient, session: Session
) -> None:
    alice, _ = _get_users(session)
    page = _make_page(session, alice, "page-order-timeline-query-count")
    _select_page(session, alice, page)
    customer = _order_customer(session, page, "timeline-query-count")
    created = client.post(
        "/api/v1/facebook/orders",
        headers=_auth(alice),
        json={
            "customer_uuid": str(customer.public_id),
            "items": [{"item_name": "Timeline count", "quantity": 1, "unit_price": 1}],
        },
    ).json()

    statement_count = 0

    def count_statement(*_args: object, **_kwargs: object) -> None:
        nonlocal statement_count
        statement_count += 1

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", count_statement)
    try:
        timeline = get_order_timeline(session, alice, created["uuid"])
    finally:
        event.remove(bind, "before_cursor_execute", count_statement)

    assert timeline is not None
    assert statement_count == 6
