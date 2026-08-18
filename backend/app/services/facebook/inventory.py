"""Transactional, Page-scoped Product inventory services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.models.auth import User
from app.models.inventory import ProductInventory, StockMovement
from app.models.orders import Order, OrderItem
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


@dataclass(frozen=True)
class TrackedOrderItem:
    order_item: OrderItem
    product: Product
    inventory: ProductInventory


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


def _products_for_order_items(
    session: Session, order: Order, items: list[OrderItem]
) -> dict[int, Product]:
    product_ids = {item.product_id for item in items if item.product_id is not None}
    if not product_ids:
        return {}
    products = (
        session.query(Product)
        .filter(
            Product.id.in_(product_ids),
            Product.facebook_page_id == order.facebook_page_id,
        )
        .all()
    )
    by_id = {product.id: product for product in products}
    if set(by_id) != product_ids:
        raise InventoryStateError("Order contains a Product outside its Facebook Page")
    return by_id


def _locked_inventories(
    session: Session, product_ids: set[int]
) -> dict[int, ProductInventory]:
    if not product_ids:
        return {}
    inventories = (
        session.query(ProductInventory)
        .filter(ProductInventory.product_id.in_(product_ids))
        .order_by(ProductInventory.product_id.asc())
        .with_for_update()
        .all()
    )
    by_product = {inventory.product_id: inventory for inventory in inventories}
    if set(by_product) != product_ids:
        raise InventoryStateError("A tracked Product has no inventory balance")
    return by_product


def consume_order_inventory(session: Session, user: User, order: Order) -> None:
    """Consume currently tracked Product stock without committing the caller transaction."""
    items = sorted(order.items, key=lambda item: item.id)
    products = _products_for_order_items(session, order, items)
    tracked_product_ids = {
        product.id for product in products.values() if product.track_inventory
    }
    inventories = _locked_inventories(session, tracked_product_ids)
    tracked_items = [
        TrackedOrderItem(item, products[item.product_id], inventories[item.product_id])
        for item in items
        if item.product_id is not None and products[item.product_id].track_inventory
    ]
    if not tracked_items:
        return

    item_ids = [record.order_item.id for record in tracked_items]
    existing_outs = (
        session.query(StockMovement)
        .filter(
            StockMovement.order_item_id.in_(item_ids),
            StockMovement.movement_type == "ORDER_OUT",
        )
        .all()
    )
    outs_by_item = {movement.order_item_id: movement for movement in existing_outs}
    pending: list[TrackedOrderItem] = []
    required_by_product: dict[int, int] = {}
    for record in tracked_items:
        item = record.order_item
        existing = outs_by_item.get(item.id)
        expected_key = f"ORDER_CONFIRM:{item.public_id}"
        if existing is not None:
            if (
                existing.order_id != order.id
                or existing.product_id != record.product.id
                or existing.quantity_delta != -item.quantity
                or existing.idempotency_key != expected_key
            ):
                raise InventoryStateError("Existing Order stock movement is inconsistent")
            continue
        pending.append(record)
        required_by_product[record.product.id] = (
            required_by_product.get(record.product.id, 0) + item.quantity
        )

    for product_id, required in required_by_product.items():
        if inventories[product_id].quantity_on_hand < required:
            raise InsufficientInventoryError("Insufficient inventory for one or more products")

    now = datetime.now(UTC)
    current_by_product = {
        product_id: inventory.quantity_on_hand for product_id, inventory in inventories.items()
    }
    movements: list[StockMovement] = []
    for record in pending:
        item = record.order_item
        quantity_before = current_by_product[record.product.id]
        quantity_after = quantity_before - item.quantity
        current_by_product[record.product.id] = quantity_after
        movements.append(
            StockMovement(
                public_id=uuid4(),
                product_id=record.product.id,
                order_id=order.id,
                order_item_id=item.id,
                movement_type="ORDER_OUT",
                quantity_delta=-item.quantity,
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                idempotency_key=f"ORDER_CONFIRM:{item.public_id}",
                note=f"Order {order.order_number} confirmed",
                created_by_id=user.id,
                created_at=now,
            )
        )

    for product_id, quantity_after in current_by_product.items():
        inventory = inventories[product_id]
        inventory.quantity_on_hand = quantity_after
        inventory.updated_at = now
        session.add(inventory)
    session.add_all(movements)
    session.flush()


def restore_order_inventory(session: Session, user: User, order: Order) -> None:
    """Reverse existing Order OUT movements without committing the caller transaction."""
    items = sorted(order.items, key=lambda item: item.id)
    item_by_id = {item.id: item for item in items}
    if not item_by_id:
        return
    outs = (
        session.query(StockMovement)
        .filter(
            StockMovement.order_item_id.in_(item_by_id),
            StockMovement.movement_type == "ORDER_OUT",
        )
        .order_by(StockMovement.order_item_id.asc())
        .all()
    )
    if not outs:
        return

    product_ids: set[int] = set()
    for movement in outs:
        item = item_by_id.get(movement.order_item_id)
        if (
            item is None
            or movement.order_id != order.id
            or item.product_id != movement.product_id
            or movement.quantity_delta >= 0
        ):
            raise InventoryStateError("Existing Order stock movement is inconsistent")
        product_ids.add(movement.product_id)

    products = (
        session.query(Product)
        .filter(
            Product.id.in_(product_ids),
            Product.facebook_page_id == order.facebook_page_id,
        )
        .all()
    )
    if {product.id for product in products} != product_ids:
        raise InventoryStateError("Order stock movement belongs to another Facebook Page")
    inventories = _locked_inventories(session, product_ids)

    existing_restores = (
        session.query(StockMovement)
        .filter(
            StockMovement.order_item_id.in_(item_by_id),
            StockMovement.movement_type == "ORDER_CANCEL_RESTORE",
        )
        .all()
    )
    restores_by_item = {movement.order_item_id: movement for movement in existing_restores}
    pending: list[StockMovement] = []
    restore_by_product: dict[int, int] = {}
    for out in outs:
        item = item_by_id[out.order_item_id]
        restore_quantity = abs(out.quantity_delta)
        existing = restores_by_item.get(item.id)
        expected_key = f"ORDER_CANCEL:{item.public_id}"
        if existing is not None:
            if (
                existing.order_id != order.id
                or existing.product_id != out.product_id
                or existing.quantity_delta != restore_quantity
                or existing.idempotency_key != expected_key
            ):
                raise InventoryStateError("Existing Order restoration movement is inconsistent")
            continue
        pending.append(out)
        restore_by_product[out.product_id] = (
            restore_by_product.get(out.product_id, 0) + restore_quantity
        )

    for product_id, restore_quantity in restore_by_product.items():
        if inventories[product_id].quantity_on_hand + restore_quantity > MAX_STOCK_QUANTITY:
            raise InventoryStateError("Order restoration exceeds supported inventory range")

    now = datetime.now(UTC)
    current_by_product = {
        product_id: inventory.quantity_on_hand for product_id, inventory in inventories.items()
    }
    movements: list[StockMovement] = []
    for out in pending:
        item = item_by_id[out.order_item_id]
        restore_quantity = abs(out.quantity_delta)
        quantity_before = current_by_product[out.product_id]
        quantity_after = quantity_before + restore_quantity
        current_by_product[out.product_id] = quantity_after
        movements.append(
            StockMovement(
                public_id=uuid4(),
                product_id=out.product_id,
                order_id=order.id,
                order_item_id=item.id,
                movement_type="ORDER_CANCEL_RESTORE",
                quantity_delta=restore_quantity,
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                idempotency_key=f"ORDER_CANCEL:{item.public_id}",
                note=f"Order {order.order_number} cancelled",
                created_by_id=user.id,
                created_at=now,
            )
        )

    for product_id, quantity_after in current_by_product.items():
        inventory = inventories[product_id]
        inventory.quantity_on_hand = quantity_after
        inventory.updated_at = now
        session.add(inventory)
    session.add_all(movements)
    session.flush()
