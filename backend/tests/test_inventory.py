"""Tests for the Page-scoped Product inventory backend foundation."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.inventory import ProductInventory, StockMovement
from app.models.products import Product
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.inventory import inventory_reconciles
from app.services.facebook.pages import select_current_page
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from app.websocket.manager import ConnectionManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key-inventory"


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
                username="alice_inventory",
                email="alice_inventory@example.com",
                password_hash=hash_password("pw"),
            ),
            User(
                username="bob_inventory",
                email="bob_inventory@example.com",
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
        session.query(User).filter(User.username == "alice_inventory").one(),
        session.query(User).filter(User.username == "bob_inventory").one(),
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
    return page


def _select_page(session: Session, user: User, page: FacebookPage) -> None:
    select_current_page(session, user, page.page_id)


def _create_product(client: TestClient, user: User, name: str = "Tracked Product") -> dict:
    response = client.post(
        "/api/v1/facebook/products",
        headers=_auth(user),
        json={"name": name, "sku": str(uuid4()), "currency": "VND", "sale_price": "10"},
    )
    assert response.status_code == 200
    return response.json()


def _inventory_path(product: dict) -> str:
    return f"/api/v1/facebook/products/{product['uuid']}/inventory"


def _enable(
    client: TestClient, user: User, product: dict, quantity: int = 10, note: str = "Opening"
):
    return client.post(
        f"{_inventory_path(product)}/enable",
        headers=_auth(user),
        json={"opening_quantity": quantity, "note": note},
    )


def _adjust(
    client: TestClient,
    user: User,
    product: dict,
    delta: int,
    *,
    note: str = "Count correction",
    key: str | None = None,
):
    return client.post(
        f"{_inventory_path(product)}/adjustments",
        headers=_auth(user),
        json={"quantity_delta": delta, "note": note, "idempotency_key": key or str(uuid4())},
    )


def test_product_defaults_to_untracked_and_get_represents_never_enabled(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-default")
    _select_page(session, alice, page)
    product = _create_product(client, alice)

    assert product["track_inventory"] is False
    response = client.get(_inventory_path(product), headers=_auth(alice))
    assert response.status_code == 200
    assert response.json() == {
        "product_uuid": product["uuid"],
        "track_inventory": False,
        "inventory_exists": False,
        "quantity_on_hand": None,
        "tracking_started_at": None,
        "updated_at": None,
    }


@pytest.mark.parametrize("opening_quantity", [0, 25])
def test_enable_creates_one_balance_and_one_opening_movement_and_reconciles(
    client: TestClient, session: Session, opening_quantity: int
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, f"inventory-enable-{opening_quantity}")
    _select_page(session, alice, page)
    product = _create_product(client, alice)

    response = _enable(client, alice, product, opening_quantity, " Initial count ")
    assert response.status_code == 200
    body = response.json()
    assert body["track_inventory"] is True
    assert body["inventory_exists"] is True
    assert body["quantity_on_hand"] == opening_quantity
    assert body["tracking_started_at"] is not None

    stored_product = session.query(Product).filter(Product.public_id == UUID(product["uuid"])).one()
    inventory = session.query(ProductInventory).filter_by(product_id=stored_product.id).one()
    movement = session.query(StockMovement).filter_by(product_id=stored_product.id).one()
    assert movement.movement_type == "OPENING"
    assert movement.quantity_delta == opening_quantity
    assert movement.quantity_before == 0
    assert movement.quantity_after == opening_quantity
    assert movement.note == "Initial count"
    assert movement.created_by_id == alice.id
    assert movement.idempotency_key == f"INVENTORY_OPENING:{inventory.public_id}"
    assert inventory_reconciles(session, inventory)


def test_enable_retry_disable_and_reenable_preserve_balance_and_opening(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-reenable")
    _select_page(session, alice, page)
    product = _create_product(client, alice)

    first = _enable(client, alice, product, 12)
    retry = _enable(client, alice, product, 999, "Ignored retry")
    assert first.status_code == retry.status_code == 200
    assert retry.json()["quantity_on_hand"] == 12

    disabled = client.post(f"{_inventory_path(product)}/disable", headers=_auth(alice))
    assert disabled.status_code == 200
    assert disabled.json()["track_inventory"] is False
    assert disabled.json()["quantity_on_hand"] == 12

    second_disable = client.post(f"{_inventory_path(product)}/disable", headers=_auth(alice))
    assert second_disable.status_code == 200
    reenabled = _enable(client, alice, product, 500)
    assert reenabled.status_code == 200
    assert reenabled.json()["quantity_on_hand"] == 12
    assert session.query(ProductInventory).count() == 1
    assert session.query(StockMovement).filter_by(movement_type="OPENING").count() == 1


def test_positive_and_negative_adjustments_have_correct_snapshots_and_reconcile(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-adjust")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 10)

    positive = _adjust(client, alice, product, 5, note=" Received correction ")
    assert positive.status_code == 200
    assert positive.json()["quantity_before"] == 10
    assert positive.json()["quantity_after"] == 15
    assert positive.json()["note"] == "Received correction"

    negative = _adjust(client, alice, product, -4)
    assert negative.status_code == 200
    assert negative.json()["quantity_before"] == 15
    assert negative.json()["quantity_after"] == 11

    inventory = session.query(ProductInventory).one()
    assert inventory.quantity_on_hand == 11
    assert inventory_reconciles(session, inventory)


def test_adjustment_is_allowed_while_disabled_without_enabling(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-disabled-adjust")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 5)
    client.post(f"{_inventory_path(product)}/disable", headers=_auth(alice))

    adjusted = _adjust(client, alice, product, 2)
    assert adjusted.status_code == 200
    state = client.get(_inventory_path(product), headers=_auth(alice)).json()
    assert state["track_inventory"] is False
    assert state["quantity_on_hand"] == 7


def test_negative_stock_is_rejected_without_partial_mutation(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-negative")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 5)

    rejected = _adjust(client, alice, product, -6)
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "Adjustment would make inventory negative"
    assert session.query(ProductInventory).one().quantity_on_hand == 5
    assert session.query(StockMovement).count() == 1


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"quantity_delta": 0, "note": "No-op", "idempotency_key": str(uuid4())}, 422),
        ({"quantity_delta": 1, "note": "   ", "idempotency_key": str(uuid4())}, 422),
        ({"quantity_delta": 1, "note": "Valid", "idempotency_key": "not-a-uuid"}, 422),
        (
            {
                "quantity_delta": 1,
                "note": "Valid",
                "idempotency_key": str(uuid4()),
                "quantity_on_hand": 100,
            },
            422,
        ),
        (
            {
                "quantity_delta": 1,
                "note": "Valid",
                "idempotency_key": str(uuid4()),
                "product_id": 1,
            },
            422,
        ),
    ],
)
def test_adjustment_schema_rejects_invalid_or_client_authoritative_fields(
    client: TestClient, session: Session, payload: dict, expected_status: int
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, f"inventory-validation-{uuid4()}")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 5)
    response = client.post(
        f"{_inventory_path(product)}/adjustments", headers=_auth(alice), json=payload
    )
    assert response.status_code == expected_status


def test_adjustment_idempotency_exact_retry_and_conflicting_retry(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-idempotency")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 10)
    key = str(uuid4())

    first = _adjust(client, alice, product, 3, note="Retry-safe", key=key)
    retry = _adjust(client, alice, product, 3, note="Retry-safe", key=key)
    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()
    assert session.query(ProductInventory).one().quantity_on_hand == 13
    assert session.query(StockMovement).filter_by(movement_type="ADJUSTMENT").count() == 1

    for delta, note in [(4, "Retry-safe"), (3, "Different note")]:
        conflict = _adjust(client, alice, product, delta, note=note, key=key)
        assert conflict.status_code == 409
        assert "different adjustment" in conflict.json()["detail"]
    assert session.query(ProductInventory).one().quantity_on_hand == 13


def test_movement_history_is_stable_paginated_filtered_and_has_no_mutation_api(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-history")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 10)
    first_adjustment = _adjust(client, alice, product, 1).json()
    second_adjustment = _adjust(client, alice, product, 2).json()

    first_page = client.get(
        f"{_inventory_path(product)}/movements?page=1&page_size=2", headers=_auth(alice)
    )
    assert first_page.status_code == 200
    assert first_page.json()["meta"] == {
        "total": 3,
        "page": 1,
        "page_size": 2,
        "has_next": True,
        "has_prev": False,
    }
    assert [item["uuid"] for item in first_page.json()["items"]] == [
        second_adjustment["uuid"],
        first_adjustment["uuid"],
    ]
    filtered = client.get(
        f"{_inventory_path(product)}/movements?movement_type=OPENING", headers=_auth(alice)
    )
    assert filtered.json()["meta"]["total"] == 1
    assert filtered.json()["items"][0]["movement_type"] == "OPENING"

    movement_uuid = first_adjustment["uuid"]
    assert client.patch(
        f"{_inventory_path(product)}/movements/{movement_uuid}",
        headers=_auth(alice),
        json={"note": "tamper"},
    ).status_code in {404, 405}
    assert client.delete(
        f"{_inventory_path(product)}/movements/{movement_uuid}", headers=_auth(alice)
    ).status_code in {404, 405}


def test_all_inventory_endpoints_are_page_scoped(client: TestClient, session: Session) -> None:
    alice, bob = _users(session)
    alice_page = _make_page(session, alice, "inventory-scope-alice")
    bob_page = _make_page(session, bob, "inventory-scope-bob")
    _select_page(session, alice, alice_page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 8)
    _select_page(session, bob, bob_page)

    calls = [
        client.get(_inventory_path(product), headers=_auth(bob)),
        _enable(client, bob, product, 99),
        client.post(f"{_inventory_path(product)}/disable", headers=_auth(bob)),
        _adjust(client, bob, product, 1),
        client.get(f"{_inventory_path(product)}/movements", headers=_auth(bob)),
    ]
    assert [response.status_code for response in calls] == [404, 404, 404, 404, 404]
    assert session.query(ProductInventory).one().quantity_on_hand == 8
    assert session.query(StockMovement).count() == 1


def test_archive_preserves_reads_and_history_but_blocks_enable_and_adjustment(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-archive")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 7)
    archived = client.delete(f"/api/v1/facebook/products/{product['uuid']}", headers=_auth(alice))
    assert archived.status_code == 200

    state = client.get(_inventory_path(product), headers=_auth(alice))
    history = client.get(f"{_inventory_path(product)}/movements", headers=_auth(alice))
    assert state.status_code == history.status_code == 200
    assert state.json()["quantity_on_hand"] == 7
    assert history.json()["meta"]["total"] == 1
    assert _enable(client, alice, product, 9).status_code == 404
    assert _adjust(client, alice, product, 1).status_code == 404


def test_product_edits_and_generic_patch_cannot_mutate_inventory_state(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-product-edit")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 6)
    movement_ids = [row.public_id for row in session.query(StockMovement).all()]

    updated = client.patch(
        f"/api/v1/facebook/products/{product['uuid']}",
        headers=_auth(alice),
        json={"name": "Renamed", "sku": "NEW-SKU", "sale_price": "99", "track_inventory": False},
    )
    assert updated.status_code == 200
    assert updated.json()["track_inventory"] is True
    assert session.query(ProductInventory).one().quantity_on_hand == 6
    assert [row.public_id for row in session.query(StockMovement).all()] == movement_ids


def test_adjustment_requires_an_existing_balance(client: TestClient, session: Session) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-no-balance")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    response = _adjust(client, alice, product, 1)
    assert response.status_code == 409
    assert response.json()["detail"] == "Inventory has not been enabled for this Product"
    assert session.query(func.count(StockMovement.id)).scalar() == 0


def test_inventory_foundation_does_not_create_order_movements(
    client: TestClient, session: Session
) -> None:
    alice, _ = _users(session)
    page = _make_page(session, alice, "inventory-no-orders")
    _select_page(session, alice, page)
    product = _create_product(client, alice)
    _enable(client, alice, product, 3)
    _adjust(client, alice, product, 1)
    assert session.query(StockMovement).filter(StockMovement.order_id.is_not(None)).count() == 0
    assert (
        session.query(StockMovement).filter(StockMovement.order_item_id.is_not(None)).count()
        == 0
    )
    assert {
        movement.movement_type for movement in session.query(StockMovement).all()
    } == {"OPENING", "ADJUSTMENT"}
