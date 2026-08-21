"""M30.2 external waybill persistence, isolation, and operation tests."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.carriers.base import CarrierCapabilities
from app.carriers.registry import CarrierRegistry
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.carriers import CarrierAccount, CarrierOperation, ExternalWaybill
from app.models.customer_core import Customer
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.inventory import StockMovement
from app.models.messenger import Conversation
from app.models.orders import Order, OrderEvent, OrderItem
from app.models.shipments import Shipment, ShipmentEvent
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.pages import select_current_page
from app.services.facebook.shipments import bind_carrier_account, update_shipment_tracking
from app.services.facebook.waybills import (
    CarrierIdempotencyConflictError,
    CarrierOperationStateError,
    build_create_waybill_request,
    finalize_create_waybill,
    prepare_create_waybill_operation,
)
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-waybills"
SECRET_KEY_FRAGMENTS = (
    "credential",
    "secret",
    "password",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
)


class WaybillProvider:
    code = "parcel-test"
    display_name = "Parcel Test"
    capabilities = CarrierCapabilities(
        supports_credentials=True,
        requires_credentials=False,
        shipment_binding=True,
        waybills=True,
        tracking=True,
    )

    def validate_credentials(self, credentials) -> None:
        if not isinstance(credentials, dict):
            raise ValueError("credentials must be an object")

    def validate_configuration(self, configuration) -> None:
        if not isinstance(configuration, dict):
            raise ValueError("configuration must be an object")


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
    db.add(
        User(
            username="waybill_operator",
            email="waybill_operator@example.com",
            password_hash=hash_password("pw"),
            full_name="Waybill Operator",
        )
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


@pytest.fixture()
def waybill_provider(monkeypatch: pytest.MonkeyPatch) -> WaybillProvider:
    provider = WaybillProvider()
    registry = CarrierRegistry()
    registry.register(provider)
    monkeypatch.setattr("app.services.facebook.waybills.carrier_registry", registry)
    return provider


def _user(db: Session) -> User:
    return db.query(User).filter_by(username="waybill_operator").one()


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def _make_pages(db: Session, user: User) -> tuple[FacebookPage, FacebookPage]:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id="fb-waybill-operator",
        access_token_encrypted=cipher.encrypt("user-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(account)
    db.flush()
    pages = (
        FacebookPage(
            facebook_account_id=account.id,
            page_id="waybill-page-a",
            name="Waybill Page A",
            is_active=True,
        ),
        FacebookPage(
            facebook_account_id=account.id,
            page_id="waybill-page-b",
            name="Waybill Page B",
            is_active=True,
        ),
    )
    db.add_all(pages)
    db.commit()
    return pages


def _select(db: Session, user: User, page: FacebookPage) -> None:
    select_current_page(db, user, page.page_id)


def _shipment(db: Session, user: User, page: FacebookPage, suffix: str) -> Shipment:
    customer = Customer(name=f"Waybill Customer {suffix}", phone="0901234567", status="ACTIVE")
    db.add(customer)
    db.flush()
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=f"waybill-psid-{suffix}",
        customer_id=customer.id,
    )
    db.add(conversation)
    db.flush()
    order = Order(
        public_id=uuid4(),
        facebook_page_id=page.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        order_number=f"WAYBILL-{suffix}",
        status="confirmed",
        payment_status="unpaid",
        shipping_status="pending",
        currency="VND",
        subtotal_amount=Decimal("25000.00"),
        discount_amount=Decimal("0.00"),
        shipping_fee=Decimal("0.00"),
        total_amount=Decimal("25000.00"),
        shipping_address="Order address that must not replace the Shipment snapshot",
        shipping_recipient_name="Changed Order Recipient",
        shipping_recipient_phone="0999999999",
        shipping_recipient_phone_normalized="0999999999",
        shipping_ward="Changed Ward",
        shipping_district="Changed District",
        shipping_province="Changed Province",
        shipping_country_code="VN",
        created_by_id=user.id,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            order_id=order.id,
            item_name="Snapshot item",
            sku="SNAP-1",
            quantity=2,
            unit_price=Decimal("12500.00"),
            line_total=Decimal("25000.00"),
        )
    )
    shipment = Shipment(
        public_id=uuid4(),
        order_id=order.id,
        shipment_number=f"SHP-WAYBILL-{suffix}",
        status="ready",
        recipient_name="Immutable Recipient",
        recipient_phone="0901234567",
        recipient_phone_normalized="0901234567",
        address_line="123 Immutable Street",
        ward="Snapshot Ward",
        district="Snapshot District",
        province="Snapshot Province",
        postal_code="700000",
        country_code="VN",
        delivery_note="Snapshot delivery note",
        cod_amount=Decimal("25000.00"),
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def _account(
    db: Session,
    page: FacebookPage,
    user: User,
    *,
    provider_code: str = "parcel-test",
    display_name: str = "Parcel Account",
    status: str = "active",
) -> CarrierAccount:
    account = CarrierAccount(
        public_id=uuid4(),
        facebook_page_id=page.id,
        provider_code=provider_code,
        display_name=display_name,
        status=status,
        credentials_encrypted="encrypted-not-a-real-secret",
        configuration={"region": "south"},
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _waybill(
    db: Session,
    shipment: Shipment,
    account: CarrierAccount,
    *,
    status: str = "created",
    is_current: bool = True,
    external_id: str = "WB-1001",
) -> ExternalWaybill:
    row = ExternalWaybill(
        public_id=uuid4(),
        facebook_page_id=shipment.order.facebook_page_id,
        shipment_id=shipment.id,
        carrier_account_id=account.id,
        provider_code=account.provider_code,
        account_public_id_snapshot=account.public_id,
        account_display_name_snapshot=account.display_name,
        external_id=external_id,
        tracking_number="TRACK-1001",
        tracking_url="https://tracking.example/TRACK-1001",
        status=status,
        created_by_id=shipment.created_by_id,
    )
    db.add(row)
    db.flush()
    if is_current:
        shipment.current_external_waybill_id = row.id
    db.commit()
    db.refresh(row)
    return row


def _operation(
    db: Session,
    shipment: Shipment,
    account: CarrierAccount,
    *,
    key: str,
    status: str,
    created_at: datetime,
    waybill: ExternalWaybill | None = None,
) -> CarrierOperation:
    row = CarrierOperation(
        public_id=uuid4(),
        facebook_page_id=shipment.order.facebook_page_id,
        shipment_id=shipment.id,
        carrier_account_id=account.id,
        external_waybill_id=waybill.id if waybill else None,
        provider_code=account.provider_code,
        account_public_id_snapshot=account.public_id,
        account_display_name_snapshot=account.display_name,
        operation_type="CREATE_WAYBILL",
        idempotency_key=key,
        request_fingerprint=(key.encode().hex() + "0" * 64)[:64],
        status=status,
        request_snapshot={"shipment_uuid": str(shipment.public_id)},
        response_snapshot={"outcome": status},
        attempted_by_id=shipment.created_by_id,
        created_at=created_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _assert_public_safe(value: object) -> None:
    serialized = json.dumps(value).lower()
    for fragment in SECRET_KEY_FRAGMENTS:
        assert fragment not in serialized

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                assert key not in {"id", "shipment_id", "carrier_account_id", "facebook_page_id"}
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)


def _business_state(db: Session, shipment: Shipment) -> dict[str, object]:
    db.refresh(shipment)
    db.refresh(shipment.order)
    return {
        "shipment": {
            "status": shipment.status,
            "carrier_code": shipment.carrier_code,
            "carrier_name": shipment.carrier_name,
            "tracking_number": shipment.tracking_number,
            "tracking_url": shipment.tracking_url,
            "shipping_fee": shipment.shipping_fee,
            "cod_amount": shipment.cod_amount,
            "note": shipment.note,
        },
        "order": {
            "status": shipment.order.status,
            "payment_status": shipment.order.payment_status,
            "shipping_status": shipment.order.shipping_status,
            "subtotal_amount": shipment.order.subtotal_amount,
            "discount_amount": shipment.order.discount_amount,
            "shipping_fee": shipment.order.shipping_fee,
            "total_amount": shipment.order.total_amount,
        },
        "shipment_events": db.query(ShipmentEvent).count(),
        "order_events": db.query(OrderEvent).count(),
        "stock_movements": db.query(StockMovement).count(),
    }


def test_manual_shipment_read_apis_have_no_false_waybill_and_keep_m29_tracking(
    client: TestClient, session: Session
) -> None:
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    shipment = _shipment(session, user, page, "MANUAL")

    updated = update_shipment_tracking(
        session,
        user,
        str(shipment.public_id),
        {
            "carrier_code": "  GHN  ",
            "carrier_name": "  Manual Carrier  ",
            "tracking_number": "  M29-TRACK  ",
            "tracking_url": "  https://tracking.example/M29-TRACK  ",
        },
    )
    assert updated is not None
    assert updated.carrier_account_id is None

    waybill = client.get(
        f"/api/v1/facebook/shipments/{shipment.public_id}/waybill", headers=_auth(user)
    )
    operations = client.get(
        f"/api/v1/facebook/shipments/{shipment.public_id}/carrier-operations",
        headers=_auth(user),
    )
    detail = client.get(f"/api/v1/facebook/shipments/{shipment.public_id}", headers=_auth(user))

    assert waybill.status_code == operations.status_code == detail.status_code == 200
    assert waybill.json() == {"item": None}
    assert operations.json() == {"items": []}
    assert detail.json()["carrier_account_uuid"] is None
    assert detail.json()["tracking_number"] == "M29-TRACK"
    assert detail.json()["carrier_name"] == "Manual Carrier"
    assert session.query(ExternalWaybill).count() == 0
    assert session.query(CarrierOperation).count() == 0


def test_waybill_reads_are_page_scoped_public_safe_and_survive_account_deactivation(
    client: TestClient, session: Session
) -> None:
    user = _user(session)
    page_a, page_b = _make_pages(session, user)
    _select(session, user, page_a)
    shipment = _shipment(session, user, page_a, "READ")
    account = _account(session, page_a, user, display_name="Historical Parcel Account")
    waybill = _waybill(session, shipment, account)
    operation = _operation(
        session,
        shipment,
        account,
        key="read-operation",
        status="succeeded",
        created_at=datetime.now(UTC),
        waybill=waybill,
    )

    account.display_name = "Renamed Account"
    account.status = "inactive"
    account.credentials_encrypted = None
    account.deactivated_at = datetime.now(UTC)
    session.commit()

    waybill_response = client.get(
        f"/api/v1/facebook/shipments/{shipment.public_id}/waybill", headers=_auth(user)
    )
    operations_response = client.get(
        f"/api/v1/facebook/shipments/{shipment.public_id}/carrier-operations",
        headers=_auth(user),
    )
    assert waybill_response.status_code == operations_response.status_code == 200
    item = waybill_response.json()["item"]
    assert item == {
        "uuid": str(waybill.public_id),
        "shipment_uuid": str(shipment.public_id),
        "provider_code": "parcel-test",
        "carrier_account_uuid": str(account.public_id),
        "carrier_account_display_name": "Historical Parcel Account",
        "external_id": "WB-1001",
        "tracking_number": "TRACK-1001",
        "tracking_url": "https://tracking.example/TRACK-1001",
        "status": "created",
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "cancelled_at": None,
    }
    operation_item = operations_response.json()["items"][0]
    assert operation_item["uuid"] == str(operation.public_id)
    assert operation_item["waybill_uuid"] == str(waybill.public_id)
    assert operation_item["carrier_account_uuid"] == str(account.public_id)
    assert operation_item["carrier_account_display_name"] == "Historical Parcel Account"
    _assert_public_safe(waybill_response.json())
    _assert_public_safe(operations_response.json())

    _select(session, user, page_b)
    assert (
        client.get(
            f"/api/v1/facebook/shipments/{shipment.public_id}/waybill", headers=_auth(user)
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/facebook/shipments/{shipment.public_id}/carrier-operations",
            headers=_auth(user),
        ).status_code
        == 404
    )


def test_prepare_operation_is_idempotent_uses_shipment_snapshot_and_is_business_neutral(
    session: Session, waybill_provider: WaybillProvider
) -> None:
    del waybill_provider
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    shipment = _shipment(session, user, page, "PREPARE")
    account = _account(session, page, user, display_name="Snapshot Account")
    assert (
        bind_carrier_account(session, user, str(shipment.public_id), str(account.public_id))
        is not None
    )
    before = _business_state(session, shipment)

    request = build_create_waybill_request(shipment)
    assert request.recipient.name == "Immutable Recipient"
    assert request.recipient.address_line == "123 Immutable Street"
    assert request.recipient.ward == "Snapshot Ward"
    assert request.recipient.province == "Snapshot Province"
    assert request.items[0].name == "Snapshot item"

    first, replayed = prepare_create_waybill_operation(
        session, user, str(shipment.public_id), " stable-key "
    )
    assert replayed is False
    assert first.status == "pending"
    assert first.idempotency_key == "stable-key"
    assert first.provider_code == "parcel-test"
    assert first.account_public_id_snapshot == account.public_id
    assert first.account_display_name_snapshot == "Snapshot Account"
    assert first.request_snapshot["recipient"]["address_line"] == "123 Immutable Street"
    assert first.request_snapshot["recipient"]["name"] == "Immutable Recipient"
    assert first.request_snapshot["items"] == [
        {"name": "Snapshot item", "sku": "SNAP-1", "quantity": 2, "unit_price": "12500.00"}
    ]
    _assert_public_safe(first.request_snapshot)

    replay, replayed = prepare_create_waybill_operation(
        session, user, str(shipment.public_id), "stable-key"
    )
    assert replayed is True
    assert replay.id == first.id
    assert session.query(CarrierOperation).count() == 1
    assert _business_state(session, shipment) == before

    shipment.address_line = "A different immutable snapshot"
    session.commit()
    with pytest.raises(
        CarrierIdempotencyConflictError,
        match="Idempotency key was already used with a different request",
    ):
        prepare_create_waybill_operation(session, user, str(shipment.public_id), "stable-key")
    assert session.query(CarrierOperation).count() == 1
    assert session.query(ExternalWaybill).count() == 0


def test_prepare_rejects_inactive_cross_page_manual_and_existing_current_waybill(
    session: Session, waybill_provider: WaybillProvider
) -> None:
    del waybill_provider
    user = _user(session)
    page_a, page_b = _make_pages(session, user)
    _select(session, user, page_a)
    shipment = _shipment(session, user, page_a, "REJECT")
    account_a = _account(session, page_a, user)
    assert (
        bind_carrier_account(session, user, str(shipment.public_id), str(account_a.public_id))
        is not None
    )

    account_a.status = "inactive"
    session.commit()
    with pytest.raises(CarrierOperationStateError, match="Carrier account is inactive"):
        prepare_create_waybill_operation(session, user, str(shipment.public_id), "inactive")
    assert session.query(CarrierOperation).count() == 0

    account_a.status = "active"
    account_b = _account(session, page_b, user, display_name="Other Page Account")
    shipment.carrier_account_id = account_b.id
    session.commit()
    with pytest.raises(CarrierOperationStateError, match="outside the current Page"):
        prepare_create_waybill_operation(session, user, str(shipment.public_id), "cross-page")
    assert session.query(CarrierOperation).count() == 0

    manual = _account(
        session,
        page_a,
        user,
        provider_code="manual",
        display_name="Manual Account",
    )
    shipment.carrier_account_id = manual.id
    session.commit()
    with pytest.raises(CarrierOperationStateError, match="does not support waybills"):
        prepare_create_waybill_operation(session, user, str(shipment.public_id), "manual")
    assert session.query(CarrierOperation).count() == 0

    shipment.carrier_account_id = account_a.id
    session.commit()
    _waybill(session, shipment, account_a)
    with pytest.raises(CarrierOperationStateError, match="already has a current waybill"):
        prepare_create_waybill_operation(session, user, str(shipment.public_id), "duplicate")
    assert session.query(CarrierOperation).count() == 0


def test_current_waybill_selection_unknown_status_and_operation_order_are_stable(
    client: TestClient, session: Session
) -> None:
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    shipment = _shipment(session, user, page, "ORDERING")
    account = _account(session, page, user)
    historical = _waybill(
        session,
        shipment,
        account,
        status="cancelled",
        is_current=False,
        external_id="WB-OLD",
    )
    current = _waybill(
        session,
        shipment,
        account,
        status="unknown",
        is_current=True,
        external_id="WB-UNKNOWN",
    )
    same_time = datetime(2025, 1, 1, tzinfo=UTC)
    first = _operation(
        session, shipment, account, key="first", status="unknown", created_at=same_time
    )
    second = _operation(
        session, shipment, account, key="second", status="failed", created_at=same_time
    )

    waybill_response = client.get(
        f"/api/v1/facebook/shipments/{shipment.public_id}/waybill", headers=_auth(user)
    )
    operations_response = client.get(
        f"/api/v1/facebook/shipments/{shipment.public_id}/carrier-operations",
        headers=_auth(user),
    )
    assert waybill_response.status_code == operations_response.status_code == 200
    assert waybill_response.json()["item"]["uuid"] == str(current.public_id)
    assert waybill_response.json()["item"]["external_id"] == "WB-UNKNOWN"
    assert waybill_response.json()["item"]["status"] == "unknown"
    assert waybill_response.json()["item"]["uuid"] != str(historical.public_id)
    items = operations_response.json()["items"]
    assert [item["uuid"] for item in items] == [str(first.public_id), str(second.public_id)]
    assert [item["status"] for item in items] == ["unknown", "failed"]
    assert items[0]["status"] != items[1]["status"]
    _assert_public_safe(items)


def test_finalize_assigns_pointer_preserves_history_and_rejects_second_current(
    session: Session, waybill_provider: WaybillProvider
) -> None:
    del waybill_provider
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    shipment = _shipment(session, user, page, "FINALIZE")
    account = _account(session, page, user)
    assert (
        bind_carrier_account(session, user, str(shipment.public_id), str(account.public_id))
        is not None
    )
    before = _business_state(session, shipment)
    operation, _ = prepare_create_waybill_operation(
        session, user, str(shipment.public_id), "finalize-one"
    )

    waybill = finalize_create_waybill(
        session,
        operation.id,
        external_id="WB-FINAL",
        tracking_number="TRACK-FINAL",
    )
    session.refresh(shipment)
    assert shipment.current_external_waybill_id == waybill.id
    assert session.query(ExternalWaybill).filter_by(shipment_id=shipment.id).count() == 1
    assert _business_state(session, shipment) == before

    second = _operation(
        session,
        shipment,
        account,
        key="finalize-two",
        status="pending",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(CarrierOperationStateError, match="already has a current waybill"):
        finalize_create_waybill(session, second.id, external_id="WB-SECOND")
    assert session.query(ExternalWaybill).filter_by(shipment_id=shipment.id).count() == 1
    assert session.get(ExternalWaybill, waybill.id) is not None


def test_mysql_two_session_finalization_serializes_current_pointer() -> None:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.startswith("mysql+pymysql://") or "test" not in database_url.lower():
        pytest.skip("requires a MySQL test DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        }
    required = {"shipments", "external_waybills", "carrier_operations"}
    if not required.issubset(tables):
        engine.dispose()
        pytest.skip("MySQL test database is not migrated through 0025")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    setup = factory()
    operation_ids: list[int] = []
    shipment_id: int | None = None
    try:
        user = setup.query(User).first()
        page = setup.query(FacebookPage).first()
        account = setup.query(CarrierAccount).filter_by(status="active").first()
        if user is None or page is None or account is None:
            pytest.skip("MySQL test database needs seeded user, Page, and active carrier account")
        shipment = _shipment(setup, user, page, f"MYSQL-{uuid4().hex[:8]}")
        shipment.carrier_account_id = account.id
        setup.commit()
        shipment_id = shipment.id
        for key in ("mysql-concurrent-a", "mysql-concurrent-b"):
            operation_ids.append(
                _operation(
                    setup,
                    shipment,
                    account,
                    key=f"{key}-{uuid4().hex}",
                    status="pending",
                    created_at=datetime.now(UTC),
                ).id
            )
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker(operation_id: int, external_id: str) -> None:
        db = factory()
        try:
            barrier.wait()
            finalize_create_waybill(db, operation_id, external_id=external_id)
            outcomes.append("created")
        except CarrierOperationStateError:
            outcomes.append("rejected")
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=(operation_ids[0], f"MYSQL-{uuid4().hex}")),
        threading.Thread(target=worker, args=(operation_ids[1], f"MYSQL-{uuid4().hex}")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    verify = factory()
    try:
        shipment = verify.get(Shipment, shipment_id)
        assert shipment is not None
        assert shipment.current_external_waybill_id is not None
        assert outcomes.count("created") == 1
        assert outcomes.count("rejected") == 1
        assert verify.query(ExternalWaybill).filter_by(shipment_id=shipment_id).count() == 1
    finally:
        verify.close()
        engine.dispose()


def test_m30_1_account_and_m29_tracking_regressions_remain_intact(
    client: TestClient, session: Session
) -> None:
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    account = _account(
        session,
        page,
        user,
        provider_code="manual",
        display_name="M30.1 Manual Account",
    )
    shipment = _shipment(session, user, page, "REGRESSION")
    before = _business_state(session, shipment)

    accounts = client.get("/api/v1/facebook/carrier-accounts", headers=_auth(user))
    assert accounts.status_code == 200
    assert accounts.json()["items"][0]["uuid"] == str(account.public_id)
    assert accounts.json()["items"][0]["configured"] is True
    _assert_public_safe(accounts.json())

    updated = update_shipment_tracking(
        session,
        user,
        str(shipment.public_id),
        {
            "carrier_code": "  GHN  ",
            "carrier_name": "  Giao Hang Nhanh  ",
            "tracking_number": "  M29-REGRESSION  ",
            "tracking_url": "  https://tracking.example/M29-REGRESSION  ",
        },
    )
    assert updated is not None
    assert updated.carrier_account_id is None
    assert updated.carrier_code == "ghn"
    assert updated.tracking_number == "M29-REGRESSION"
    assert session.query(ShipmentEvent).filter_by(event_type="TRACKING_UPDATED").count() == 1
    after = _business_state(session, shipment)
    assert after["order"] == before["order"]
    assert after["order_events"] == before["order_events"]
    assert after["stock_movements"] == before["stock_movements"]
    assert session.query(ExternalWaybill).count() == 0
    assert session.query(CarrierOperation).count() == 0
