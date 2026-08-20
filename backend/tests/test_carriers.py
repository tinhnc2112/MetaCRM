"""M30.1 carrier registry, Page-scoped account, and Shipment binding tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.carriers.base import CarrierCapabilities
from app.carriers.registry import CarrierRegistry
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.carriers import CarrierAccount
from app.models.customer_core import Customer
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.inventory import StockMovement
from app.models.messenger import Conversation
from app.models.orders import Order
from app.models.shipments import Shipment, ShipmentEvent
from app.services.facebook.carrier_accounts import create_carrier_account
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.pages import select_current_page
from app.services.facebook.shipments import bind_carrier_account
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-carriers"


class CredentialCarrierProvider:
    code = "  Parcel-Test  "
    display_name = "Parcel Test"
    capabilities = CarrierCapabilities(
        supports_credentials=True,
        requires_credentials=False,
        shipment_binding=True,
        tracking=True,
        rates=True,
    )

    def validate_credentials(self, credentials) -> None:
        if not isinstance(credentials, dict):
            raise ValueError("credentials must be an object")
        if credentials and not credentials.get("api_key"):
            raise ValueError("api_key is required")

    def validate_configuration(self, configuration) -> None:
        if not isinstance(configuration, dict):
            raise ValueError("configuration must be an object")
        secret_fragments = ("credential", "secret", "password", "token", "api_key", "apikey")
        for key in configuration:
            normalized = str(key).lower().replace("-", "_")
            if any(fragment in normalized for fragment in secret_fragments):
                raise ValueError("configuration cannot contain credentials or secrets")


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    db.add(
        User(
            username="carrier_operator",
            email="carrier_operator@example.com",
            password_hash=hash_password("pw"),
            full_name="Carrier Operator",
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
def credential_provider(monkeypatch: pytest.MonkeyPatch) -> CredentialCarrierProvider:
    provider = CredentialCarrierProvider()
    registry = CarrierRegistry()
    registry.register(provider)
    monkeypatch.setattr("app.services.facebook.carrier_accounts.carrier_registry", registry)
    return provider


def _user(db: Session) -> User:
    return db.query(User).filter_by(username="carrier_operator").one()


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def _make_pages(db: Session, user: User) -> tuple[FacebookPage, FacebookPage]:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id="fb-carrier-operator",
        access_token_encrypted=cipher.encrypt("user-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(account)
    db.flush()
    pages = (
        FacebookPage(facebook_account_id=account.id, page_id="carrier-page-a", name="Carrier Page A"),
        FacebookPage(facebook_account_id=account.id, page_id="carrier-page-b", name="Carrier Page B"),
    )
    db.add_all(pages)
    db.commit()
    return pages


def _select(db: Session, user: User, page: FacebookPage) -> None:
    select_current_page(db, user, page.page_id)


def _create_account(
    client: TestClient,
    user: User,
    *,
    name: str,
    credentials: dict | None = None,
    configuration: dict | None = None,
):
    return client.post(
        "/api/v1/facebook/carrier-accounts",
        headers=_auth(user),
        json={
            "provider_code": " PARCEL-TEST ",
            "display_name": f"  {name}  ",
            "credentials": credentials,
            "configuration": configuration or {},
        },
    )


def _assert_write_only(body: dict, *secrets: str) -> None:
    serialized = json.dumps(body)
    assert "credentials" not in body
    assert "credentials_encrypted" not in body
    for secret in secrets:
        assert secret not in serialized


def _shipment(db: Session, user: User, page: FacebookPage, suffix: str) -> Shipment:
    customer = Customer(name=f"Carrier Customer {suffix}", phone="0901234567", status="ACTIVE")
    db.add(customer)
    db.flush()
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=f"carrier-psid-{suffix}",
        customer_id=customer.id,
    )
    db.add(conversation)
    db.flush()
    order = Order(
        public_id=uuid4(),
        facebook_page_id=page.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        order_number=f"CARRIER-{suffix}",
        status="confirmed",
        payment_status="unpaid",
        shipping_status="pending",
        currency="VND",
        subtotal_amount=0,
        discount_amount=0,
        shipping_fee=0,
        total_amount=0,
        created_by_id=user.id,
    )
    db.add(order)
    db.flush()
    shipment = Shipment(
        public_id=uuid4(),
        order_id=order.id,
        shipment_number=f"SHP-CARRIER-{suffix}",
        status="ready",
        recipient_name="Carrier Recipient",
        recipient_phone="0901234567",
        recipient_phone_normalized="0901234567",
        address_line="123 Carrier Street",
        ward="Ward 1",
        district="District 1",
        province="HCMC",
        country_code="VN",
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def test_provider_registry_normalizes_codes_and_manual_capabilities(client: TestClient, session: Session) -> None:
    registry = CarrierRegistry()
    provider = CredentialCarrierProvider()
    registry.register(provider)
    assert registry.get(" parcel-test ") is provider
    assert registry.list() == (provider,)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(provider)

    user = _user(session)
    response = client.get("/api/v1/facebook/carriers/providers", headers=_auth(user))
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "code": "manual",
                "display_name": "Manual",
                "capabilities": {
                    "supports_credentials": False,
                    "requires_credentials": False,
                    "shipment_binding": True,
                    "waybills": False,
                    "labels": False,
                    "tracking": False,
                    "rates": False,
                    "webhooks": False,
                },
            }
        ]
    }


def test_unknown_provider_is_rejected(client: TestClient, session: Session) -> None:
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    response = client.post(
        "/api/v1/facebook/carrier-accounts",
        headers=_auth(user),
        json={"provider_code": "unknown", "display_name": "Unknown", "configuration": {}},
    )
    assert response.status_code == 422
    assert session.query(CarrierAccount).count() == 0


def test_account_crud_page_scope_security_and_stock_neutrality(
    client: TestClient,
    session: Session,
    credential_provider: CredentialCarrierProvider,
) -> None:
    del credential_provider
    user = _user(session)
    page_a, page_b = _make_pages(session, user)
    _select(session, user, page_a)
    movement_count = session.query(StockMovement).count()
    secret = "m30-create-secret"

    created_response = _create_account(
        client,
        user,
        name="Page A Parcel",
        credentials={"api_key": secret},
        configuration={"region": "south"},
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["provider_code"] == "  Parcel-Test  "
    assert created["display_name"] == "Page A Parcel"
    assert created["configuration"] == {"region": "south"}
    assert created["configured"] is True
    _assert_write_only(created, secret)

    row = session.query(CarrierAccount).one()
    assert row.facebook_page_id == page_a.id
    assert row.credentials_encrypted and row.credentials_encrypted != secret
    assert secret not in row.credentials_encrypted
    assert json.loads(TokenCipher(TEST_TOKEN_KEY).decrypt(row.credentials_encrypted)) == {"api_key": secret}

    listed = client.get("/api/v1/facebook/carrier-accounts", headers=_auth(user))
    detail = client.get(f"/api/v1/facebook/carrier-accounts/{created['uuid']}", headers=_auth(user))
    assert listed.status_code == detail.status_code == 200
    assert [item["uuid"] for item in listed.json()["items"]] == [created["uuid"]]
    _assert_write_only(listed.json()["items"][0], secret)
    _assert_write_only(detail.json(), secret)

    updated = client.patch(
        f"/api/v1/facebook/carrier-accounts/{created['uuid']}",
        headers=_auth(user),
        json={"display_name": "  Page A Parcel Updated  ", "configuration": {"region": "north"}},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Page A Parcel Updated"
    assert updated.json()["configuration"] == {"region": "north"}

    _select(session, user, page_b)
    assert client.get("/api/v1/facebook/carrier-accounts", headers=_auth(user)).json() == {"items": []}
    assert client.get(
        f"/api/v1/facebook/carrier-accounts/{created['uuid']}", headers=_auth(user)
    ).status_code == 404
    assert client.patch(
        f"/api/v1/facebook/carrier-accounts/{created['uuid']}",
        headers=_auth(user),
        json={"display_name": "Cross Page"},
    ).status_code == 404
    assert client.put(
        f"/api/v1/facebook/carrier-accounts/{created['uuid']}/credentials",
        headers=_auth(user),
        json={"credentials": {"api_key": "cross-page"}},
    ).status_code == 404
    assert client.post(
        f"/api/v1/facebook/carrier-accounts/{created['uuid']}/deactivate", headers=_auth(user)
    ).status_code == 404

    _select(session, user, page_a)
    deactivated = client.post(
        f"/api/v1/facebook/carrier-accounts/{created['uuid']}/deactivate", headers=_auth(user)
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "inactive"
    assert deactivated.json()["configured"] is False
    assert deactivated.json()["deactivated_at"] is not None
    readable = client.get(f"/api/v1/facebook/carrier-accounts/{created['uuid']}", headers=_auth(user))
    assert readable.status_code == 200
    assert readable.json()["status"] == "inactive"
    assert session.query(StockMovement).count() == movement_count


def test_credential_replacement_is_write_only_and_configuration_rejects_secrets(
    client: TestClient,
    session: Session,
    credential_provider: CredentialCarrierProvider,
) -> None:
    del credential_provider
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    created = _create_account(client, user, name="Credential Account", configuration={}).json()
    assert created["configured"] is False

    for configuration in (
        {"api_key": "leak"},
        {"access-token": "leak"},
        {"nested_password": "leak"},
        {"nested": {"client_secret": "leak"}},
        {"regions": [{"auth token": "leak"}]},
    ):
        rejected = client.patch(
            f"/api/v1/facebook/carrier-accounts/{created['uuid']}",
            headers=_auth(user),
            json={"configuration": configuration},
        )
        assert rejected.status_code == 422

    replacement = "m30-replacement-secret"
    response = client.put(
        f"/api/v1/facebook/carrier-accounts/{created['uuid']}/credentials",
        headers=_auth(user),
        json={"credentials": {"api_key": replacement}},
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    _assert_write_only(response.json(), replacement)
    row = session.query(CarrierAccount).filter_by(public_id=UUID(created["uuid"])).one()
    assert replacement not in row.credentials_encrypted
    assert json.loads(TokenCipher(TEST_TOKEN_KEY).decrypt(row.credentials_encrypted)) == {
        "api_key": replacement
    }


def test_multiple_same_provider_accounts_are_allowed_and_isolated_by_page(
    client: TestClient,
    session: Session,
    credential_provider: CredentialCarrierProvider,
) -> None:
    del credential_provider
    user = _user(session)
    page_a, page_b = _make_pages(session, user)
    _select(session, user, page_a)
    first = _create_account(client, user, name="A One", configuration={})
    second = _create_account(client, user, name="A Two", configuration={})
    assert first.status_code == second.status_code == 201
    assert first.json()["uuid"] != second.json()["uuid"]
    assert {item["display_name"] for item in client.get(
        "/api/v1/facebook/carrier-accounts", headers=_auth(user)
    ).json()["items"]} == {"A One", "A Two"}

    _select(session, user, page_b)
    third = _create_account(client, user, name="B One", configuration={})
    assert third.status_code == 201
    assert [item["display_name"] for item in client.get(
        "/api/v1/facebook/carrier-accounts", headers=_auth(user)
    ).json()["items"]] == ["B One"]

    _select(session, user, page_a)
    assert {item["display_name"] for item in client.get(
        "/api/v1/facebook/carrier-accounts", headers=_auth(user)
    ).json()["items"]} == {"A One", "A Two"}


def test_shipment_binding_requires_same_page_and_manual_shipments_remain_unbound(
    session: Session,
    credential_provider: CredentialCarrierProvider,
) -> None:
    user = _user(session)
    page_a, page_b = _make_pages(session, user)
    _select(session, user, page_a)
    account_a = create_carrier_account(
        session,
        user,
        provider_code=credential_provider.code,
        display_name="Page A Account",
        credentials={"api_key": "a"},
        configuration={},
    )
    shipment_a = _shipment(session, user, page_a, "A")
    assert shipment_a.carrier_account_id is None

    bound = bind_carrier_account(session, user, str(shipment_a.public_id), str(account_a.public_id))
    assert bound is not None
    assert bound.carrier_account_id == account_a.id

    _select(session, user, page_b)
    account_b = create_carrier_account(
        session,
        user,
        provider_code=credential_provider.code,
        display_name="Page B Account",
        credentials={"api_key": "b"},
        configuration={},
    )
    _select(session, user, page_a)
    assert bind_carrier_account(
        session, user, str(shipment_a.public_id), str(account_b.public_id)
    ) is None
    session.refresh(shipment_a)
    assert shipment_a.carrier_account_id == account_a.id

    cleared = bind_carrier_account(session, user, str(shipment_a.public_id), None)
    assert cleared is not None
    assert cleared.carrier_account_id is None


def test_m29_manual_tracking_regression_is_unbound_and_stock_neutral(session: Session) -> None:
    user = _user(session)
    page, _ = _make_pages(session, user)
    _select(session, user, page)
    shipment = _shipment(session, user, page, "M29")
    movement_count = session.query(StockMovement).count()

    from app.services.facebook.shipments import update_shipment_tracking

    updated = update_shipment_tracking(
        session,
        user,
        str(shipment.public_id),
        {
            "carrier_code": "  GHN  ",
            "carrier_name": "  Giao Hang Nhanh  ",
            "tracking_number": "  M29-TRACK  ",
            "tracking_url": "  https://tracking.example/M29-TRACK  ",
        },
    )
    assert updated is not None
    assert updated.carrier_account_id is None
    assert updated.carrier_code == "ghn"
    assert updated.carrier_name == "Giao Hang Nhanh"
    assert updated.tracking_number == "M29-TRACK"
    assert session.query(ShipmentEvent).filter_by(event_type="TRACKING_UPDATED").count() == 1
    assert session.query(StockMovement).count() == movement_count
