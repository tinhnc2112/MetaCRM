"""Transactional, Page-scoped Product inventory services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.models.auth import User
from app.models.inventory import ProductInventory, StockMovement
from app.models.products import Product
from app.schemas.inventory import MAX_STOCK_QUANTITY
from app.services.facebook.conversations import PaginatedResult
from app.services.facebook.pages import get_current_page
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class InventoryStateError(ValueError):
    """Raised when an inventory operation conflicts with current state."""


class InventoryProductUnavailableError(ValueError):
    """Raised when an archived Product cannot be mutated."""


class InsufficientInventoryError(ValueError):
    """Raised when an adjustment would make stock negative."""


class InventoryIdempotencyConflictError(ValueError):
    """Raised when an operation key is reused for a different mutation."""


def _product_for_current_page(
    session: Session,
    user: User,
    product_uuid: str,
    *,
    lock: bool = False,
) -> Product | None:
    page = get_current_page(session, user)
    if page is None:
        return None
    try:
        public_id = UUID(product_uuid)
    except ValueError:
        return None
    query = session.query(Product).filter(
        Product.public_id == public_id,
        Product.facebook_page_id == page.id,
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def _inventory_for_product(
    session: Session, product_id: int, *, lock: bool = False
) -> ProductInventory | None:
    query = session.query(ProductInventory).filter(ProductInventory.product_id == product_id)
    if lock:
        query = query.with_for_update()
    return query.first()


def get_product_inventory(
    session: Session, user: User, product_uuid: str
) -> tuple[Product, ProductInventory | None] | None:
    product = _product_for_current_page(session, user, product_uuid)
    if product is None:
        return None
    return product, _inventory_for_product(session, product.id)


def enable_product_inventory(
    session: Session,
    user: User,
    product_uuid: str,
    *,
    opening_quantity: int,
    note: str | None,
) -> tuple[Product, ProductInventory] | None:
    product = _product_for_current_page(session, user, product_uuid, lock=True)
    if product is None:
        return None
    if product.deleted_at is not None or not product.is_active:
        raise InventoryProductUnavailableError("Product not found")

    inventory = _inventory_for_product(session, product.id, lock=True)
    if inventory is not None:
        product.track_inventory = True
        session.add(product)
        session.commit()
        session.refresh(product)
        session.refresh(inventory)
        return product, inventory

    now = datetime.now(UTC)
    inventory = ProductInventory(
        public_id=uuid4(),
        product_id=product.id,
        quantity_on_hand=opening_quantity,
        tracking_started_at=now,
        created_at=now,
        updated_at=now,
    )
    movement = StockMovement(
        public_id=uuid4(),
        product_id=product.id,
        movement_type="OPENING",
        quantity_delta=opening_quantity,
        quantity_before=0,
        quantity_after=opening_quantity,
        idempotency_key=f"INVENTORY_OPENING:{inventory.public_id}",
        note=note,
        created_by_id=user.id,
        created_at=now,
    )
    product.track_inventory = True
    session.add_all([product, inventory, movement])
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        recovered_product = _product_for_current_page(session, user, product_uuid, lock=True)
        if recovered_product is None:
            raise
        recovered_inventory = _inventory_for_product(session, recovered_product.id, lock=True)
        if recovered_inventory is None:
            raise
        opening_count = (
            session.query(func.count(StockMovement.id))
            .filter(
                StockMovement.product_id == recovered_product.id,
                StockMovement.movement_type == "OPENING",
            )
            .scalar()
        )
        if opening_count != 1:
            raise
        recovered_product.track_inventory = True
        session.commit()
        return recovered_product, recovered_inventory

    session.refresh(product)
    session.refresh(inventory)
    return product, inventory


def disable_product_inventory(
    session: Session, user: User, product_uuid: str
) -> tuple[Product, ProductInventory | None] | None:
    product = _product_for_current_page(session, user, product_uuid, lock=True)
    if product is None:
        return None
    inventory = _inventory_for_product(session, product.id, lock=True)
    product.track_inventory = False
    session.add(product)
    session.commit()
    session.refresh(product)
    if inventory is not None:
        session.refresh(inventory)
    return product, inventory


def _same_adjustment(
    movement: StockMovement, *, product_id: int, quantity_delta: int, note: str
) -> bool:
    return (
        movement.product_id == product_id
        and movement.movement_type == "ADJUSTMENT"
        and movement.quantity_delta == quantity_delta
        and movement.note == note
    )


def adjust_product_inventory(
    session: Session,
    user: User,
    product_uuid: str,
    *,
    quantity_delta: int,
    note: str,
    operation_id: UUID,
) -> StockMovement | None:
    product = _product_for_current_page(session, user, product_uuid)
    if product is None:
        return None
    if product.deleted_at is not None or not product.is_active:
        raise InventoryProductUnavailableError("Product not found")

    inventory = _inventory_for_product(session, product.id, lock=True)
    if inventory is None:
        raise InventoryStateError("Inventory has not been enabled for this Product")

    idempotency_key = f"INVENTORY_ADJUSTMENT:{operation_id}"
    existing = (
        session.query(StockMovement)
        .filter(StockMovement.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        if not _same_adjustment(
            existing, product_id=product.id, quantity_delta=quantity_delta, note=note
        ):
            raise InventoryIdempotencyConflictError(
                "Idempotency key was already used for a different adjustment"
            )
        return existing

    quantity_before = inventory.quantity_on_hand
    quantity_after = quantity_before + quantity_delta
    if quantity_after < 0:
        raise InsufficientInventoryError("Adjustment would make inventory negative")
    if quantity_after > MAX_STOCK_QUANTITY:
        raise InventoryStateError("Adjustment exceeds supported inventory range")

    now = datetime.now(UTC)
    movement = StockMovement(
        public_id=uuid4(),
        product_id=product.id,
        movement_type="ADJUSTMENT",
        quantity_delta=quantity_delta,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        idempotency_key=idempotency_key,
        note=note,
        created_by_id=user.id,
        created_at=now,
    )
    inventory.quantity_on_hand = quantity_after
    inventory.updated_at = now
    session.add_all([inventory, movement])
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = (
            session.query(StockMovement)
            .filter(StockMovement.idempotency_key == idempotency_key)
            .first()
        )
        if existing is None:
            raise
        if not _same_adjustment(
            existing, product_id=product.id, quantity_delta=quantity_delta, note=note
        ):
            raise InventoryIdempotencyConflictError(
                "Idempotency key was already used for a different adjustment"
            ) from exc
        return existing
    session.refresh(movement)
    return movement


def list_inventory_movements(
    session: Session,
    user: User,
    product_uuid: str,
    *,
    page: int,
    page_size: int,
    movement_type: str | None,
) -> PaginatedResult[StockMovement] | None:
    product = _product_for_current_page(session, user, product_uuid)
    if product is None:
        return None
    query = session.query(StockMovement).filter(StockMovement.product_id == product.id)
    if movement_type is not None:
        query = query.filter(StockMovement.movement_type == movement_type)
    total = query.count()
    items = (
        query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def inventory_reconciles(session: Session, inventory: ProductInventory) -> bool:
    movement_total = (
        session.query(func.coalesce(func.sum(StockMovement.quantity_delta), 0))
        .filter(StockMovement.product_id == inventory.product_id)
        .scalar()
    )
    return int(movement_total or 0) == inventory.quantity_on_hand
