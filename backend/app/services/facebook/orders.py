"""Customer-centric order services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum, StrEnum
from uuid import UUID, uuid4

from app.models.auth import User
from app.models.customer_core import Customer
from app.models.inventory import StockMovement
from app.models.messenger import Conversation
from app.models.orders import Order, OrderEvent, OrderItem
from app.models.shipments import Shipment, ShipmentEvent
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.conversations import PaginatedResult, get_conversation_for_user
from app.services.facebook.inventory import consume_order_inventory, restore_order_inventory
from app.services.facebook.pages import get_current_page
from app.services.facebook.products import resolve_product_for_order_item
from app.utils.phone import normalize_phone
from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, noload

MONEY_QUANTUM = Decimal("0.01")
MAX_MONEY = Decimal("9999999999.99")
ORDER_STATUSES = {"draft", "confirmed", "cancelled"}
PAYMENT_STATUSES = {"unpaid", "partial", "paid", "refunded"}
SHIPPING_STATUSES = {"pending", "packed", "shipped", "delivered", "cancelled"}
ORDER_STATUS_TRANSITIONS = {
    "draft": {"draft", "confirmed", "cancelled"},
    "confirmed": {"confirmed", "cancelled"},
    "cancelled": {"cancelled"},
}


class InvalidOrderTransitionError(ValueError):
    """Raised when an Order status transition is outside the lifecycle graph."""


class OrderIdempotencyConflictError(ValueError):
    """Raised when an Order creation key is reused for a different request."""


class ShippingDestinationLockedError(ValueError):
    """Raised when fulfillment state makes the shipping snapshot immutable."""


class OrderOperationalQueue(StrEnum):
    DRAFT = "draft"
    NEEDS_PAYMENT = "needs_payment"
    NEEDS_PACKING = "needs_packing"
    PACKED = "packed"
    IN_TRANSIT = "in_transit"
    SHIPPING_ISSUE = "shipping_issue"
    CANCELLED = "cancelled"


class OrderEventType(StrEnum):
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    PAYMENT_STATUS_CHANGED = "PAYMENT_STATUS_CHANGED"
    SHIPPING_STATUS_CHANGED = "SHIPPING_STATUS_CHANGED"


IDEMPOTENCY_CONFLICT_MESSAGE = (
    "Idempotency key was already used for a different order request."
)
IDEMPOTENCY_CONSTRAINT_NAME = "uq_orders_page_creator_idempotency_key"


@dataclass(frozen=True)
class OrderTotals:
    subtotal_amount: Decimal
    total_amount: Decimal
    line_totals: list[Decimal]


@dataclass(frozen=True)
class ShippingDestinationData:
    recipient_name: str | None
    recipient_phone: str | None
    address_line: str | None
    ward: str | None
    district: str | None
    province: str | None
    postal_code: str | None
    country_code: str
    note: str | None
    is_complete: bool


@dataclass(frozen=True)
class CustomerOrderSummary:
    order_count: int
    total_spend: Decimal
    latest_order_at: datetime | None


@dataclass(frozen=True)
class OrderListRecord:
    order: Order
    item_count: int
    customer_uuid: UUID
    customer_name: str | None
    conversation_uuid: UUID | None


@dataclass(frozen=True)
class OrderOperationalSummary:
    all: int
    draft: int
    needs_payment: int
    needs_packing: int
    packed: int
    in_transit: int
    shipping_issue: int
    cancelled: int


@dataclass(frozen=True)
class OrderEventTimelineRecord:
    public_id: UUID
    event_type: str
    from_value: str | None
    to_value: str | None
    actor_name: str | None
    actor_email: str | None
    created_at: datetime
    sort_id: int


@dataclass(frozen=True)
class InventoryMovementTimelineRecord:
    public_id: UUID
    movement_type: str
    product_name: str
    sku: str | None
    quantity_delta: int
    quantity_before: int
    quantity_after: int
    actor_name: str | None
    actor_email: str | None
    created_at: datetime
    sort_id: int


@dataclass(frozen=True)
class ShipmentEventTimelineRecord:
    public_id: UUID
    shipment_uuid: UUID
    shipment_number: str
    event_type: str
    from_value: str | None
    to_value: str | None
    actor_name: str | None
    actor_email: str | None
    created_at: datetime
    sort_id: int


OrderTimelineRecord = (
    OrderEventTimelineRecord | InventoryMovementTimelineRecord | ShipmentEventTimelineRecord
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _money(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        amount = Decimal("0")
    elif isinstance(value, Decimal):
        amount = value
    else:
        amount = Decimal(str(value))
    if amount > MAX_MONEY:
        raise ValueError("money amount exceeds Numeric(12, 2) capacity")
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _normalise_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalise_shipping_input(
    value: Mapping[str, object] | None,
    *,
    legacy_address: str | None = None,
    customer: Customer | None = None,
) -> dict[str, str | None] | None:
    if value is None:
        raw: Mapping[str, object] = {
            "recipient_name": customer.name if customer is not None else None,
            "recipient_phone": customer.phone if customer is not None else None,
            "address_line": legacy_address
            or (customer.default_address if customer is not None else None),
        }
    else:
        raw = value

    recipient_name = _normalise_text(raw.get("recipient_name"))  # type: ignore[arg-type]
    recipient_phone = _normalise_text(raw.get("recipient_phone"))  # type: ignore[arg-type]
    address_line = _normalise_text(raw.get("address_line"))  # type: ignore[arg-type]
    ward = _normalise_text(raw.get("ward"))  # type: ignore[arg-type]
    district = _normalise_text(raw.get("district"))  # type: ignore[arg-type]
    province = _normalise_text(raw.get("province"))  # type: ignore[arg-type]
    postal_code = _normalise_text(raw.get("postal_code"))  # type: ignore[arg-type]
    note = _normalise_text(raw.get("note"))  # type: ignore[arg-type]
    meaningful = (
        recipient_name,
        recipient_phone,
        address_line,
        ward,
        district,
        province,
        postal_code,
        note,
    )
    if not any(meaningful):
        return None

    country_code = _normalise_text(raw.get("country_code")) or "VN"  # type: ignore[arg-type]
    country_code = country_code.upper()
    if len(country_code) != 2 or any(
        character < "A" or character > "Z" for character in country_code
    ):
        raise ValueError("country_code must be a 2-letter code")
    normalized_phone = (
        normalize_phone(recipient_phone, country_code=country_code)
        if recipient_phone is not None
        else None
    )
    return {
        "recipient_name": recipient_name,
        "recipient_phone": recipient_phone,
        "recipient_phone_normalized": normalized_phone,
        "address_line": address_line,
        "ward": ward,
        "district": district,
        "province": province,
        "postal_code": postal_code,
        "country_code": country_code,
        "note": note,
    }


def _shipping_fingerprint_value(
    value: Mapping[str, object] | None,
    legacy_address: str | None,
) -> dict[str, str | None] | None:
    normalized = _normalise_shipping_input(value, legacy_address=legacy_address)
    if normalized is None:
        return None
    normalized = dict(normalized)
    normalized.pop("recipient_phone", None)
    return normalized


def shipping_destination_for_order(order: Order) -> ShippingDestinationData | None:
    meaningful = (
        order.shipping_recipient_name,
        order.shipping_recipient_phone,
        order.shipping_address,
        order.shipping_ward,
        order.shipping_district,
        order.shipping_province,
        order.shipping_postal_code,
        order.shipping_note,
    )
    if not any(meaningful):
        return None
    complete = all(
        (
            order.shipping_recipient_name,
            order.shipping_recipient_phone_normalized,
            order.shipping_address,
            order.shipping_ward,
            order.shipping_district,
            order.shipping_province,
        )
    )
    return ShippingDestinationData(
        recipient_name=order.shipping_recipient_name,
        recipient_phone=order.shipping_recipient_phone,
        address_line=order.shipping_address,
        ward=order.shipping_ward,
        district=order.shipping_district,
        province=order.shipping_province,
        postal_code=order.shipping_postal_code,
        country_code=order.shipping_country_code or "VN",
        note=order.shipping_note,
        is_complete=complete,
    )


def _apply_shipping_destination(
    order: Order,
    destination: dict[str, str | None] | None,
) -> None:
    values = destination or {}
    order.shipping_recipient_name = values.get("recipient_name")
    order.shipping_recipient_phone = values.get("recipient_phone")
    order.shipping_recipient_phone_normalized = values.get("recipient_phone_normalized")
    order.shipping_address = values.get("address_line")
    order.shipping_ward = values.get("ward")
    order.shipping_district = values.get("district")
    order.shipping_province = values.get("province")
    order.shipping_postal_code = values.get("postal_code")
    order.shipping_country_code = values.get("country_code")
    order.shipping_note = values.get("note")


def _shipping_destination_is_locked(order: Order) -> bool:
    if order.status == "cancelled" or _has_active_shipments(order):
        return True
    if _has_shipments(order):
        return False
    return order.shipping_status in {
        "shipped",
        "delivered",
        "cancelled",
    }


def _has_shipments(order: Order) -> bool:
    return any(shipment is not None for shipment in order.shipments)


def _has_active_shipments(order: Order) -> bool:
    return any(shipment.status != "cancelled" for shipment in order.shipments)


def normalize_order_idempotency_key(value: str | None) -> str | None:
    """Return the canonical UUID key accepted by POST Order creation."""
    if value is None:
        return None
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Idempotency-Key must be a valid UUID") from exc


def _canonical_uuid(value: object) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError:
        return str(value)


def _canonical_fingerprint_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(_money(value), "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _canonical_fingerprint_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_fingerprint_value(item) for item in value]
    return value


def build_order_create_fingerprint(
    *,
    customer_uuid: str,
    conversation_uuid: str | None,
    items: Sequence[Mapping[str, object]],
    status: str = "draft",
    payment_status: str = "unpaid",
    shipping_status: str = "pending",
    currency: str = "VND",
    discount_amount: Decimal | int | float | str = Decimal("0"),
    shipping_fee: Decimal | int | float | str = Decimal("0"),
    shipping_address: str | None = None,
    shipping_destination: Mapping[str, object] | None = None,
    note: str | None = None,
) -> str:
    """Fingerprint the normalized business inputs that drive a new Order."""
    canonical_items: list[dict[str, object]] = []
    for item in items:
        product_uuid = _canonical_uuid(item.get("product_uuid"))
        canonical_item: dict[str, object] = {
            "product_uuid": product_uuid,
            "quantity": int(item["quantity"]),
            "unit_price": (
                None if item.get("unit_price") is None else _money(item["unit_price"])
            ),
            "note": _normalise_text(item.get("note")),  # type: ignore[arg-type]
        }
        if product_uuid is None:
            canonical_item["item_name"] = _normalise_text(item.get("item_name"))  # type: ignore[arg-type]
            canonical_item["sku"] = _normalise_text(item.get("sku"))  # type: ignore[arg-type]
        canonical_items.append(canonical_item)

    canonical_request = _canonical_fingerprint_value(
        {
            "customer_uuid": _canonical_uuid(customer_uuid),
            "conversation_uuid": _canonical_uuid(conversation_uuid),
            "items": canonical_items,
            "status": status.strip().lower(),
            "payment_status": payment_status.strip().lower(),
            "shipping_status": shipping_status.strip().lower(),
            "currency": (currency or "VND").strip().upper() or "VND",
            "discount_amount": _money(discount_amount),
            "shipping_fee": _money(shipping_fee),
            "shipping_destination": _shipping_fingerprint_value(
                shipping_destination,
                shipping_address,
            ),
            "note": _normalise_text(note),
        }
    )
    encoded = json.dumps(
        canonical_request,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _current_page(session: Session, user: User):
    return get_current_page(session, user)


def _customer_on_page(session: Session, customer_id: int, page_id: int) -> bool:
    return (
        session.query(Conversation.id)
        .filter(
            Conversation.customer_id == customer_id,
            Conversation.facebook_page_id == page_id,
            Conversation.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def _order_conversation_is_page_consistent(page_id: int):
    return or_(
        Order.conversation_id.is_(None),
        Order.conversation.has(
            and_(
                Conversation.facebook_page_id == page_id,
                Conversation.customer_id == Order.customer_id,
            )
        ),
    )


def _resolve_customer_for_page(session: Session, user: User, customer_uuid: str) -> Customer | None:
    page = _current_page(session, user)
    if page is None:
        return None
    try:
        public_id = UUID(customer_uuid)
    except ValueError:
        return None
    customer = (
        session.query(Customer)
        .filter(
            Customer.public_id == public_id,
            Customer.deleted_at.is_(None),
            Customer.merged_into_customer_id.is_(None),
        )
        .first()
    )
    if customer is None or not _customer_on_page(session, customer.id, page.id):
        return None
    return customer


def _resolve_order_for_page(
    session: Session,
    user: User,
    order_uuid: str,
    *,
    lock: bool = False,
    load_items: bool = True,
) -> Order | None:
    page = _current_page(session, user)
    if page is None:
        return None
    try:
        public_id = UUID(order_uuid)
    except ValueError:
        return None
    query = (
        session.query(Order)
        .filter(
            Order.public_id == public_id,
            Order.facebook_page_id == page.id,
            Order.deleted_at.is_(None),
            _order_conversation_is_page_consistent(page.id),
        )
    )
    if not load_items:
        query = query.options(noload(Order.items), noload(Order.shipments))
    if lock:
        query = query.with_for_update()
    return query.first()


def _validate_status(status: str, allowed: set[str], field_name: str) -> str:
    cleaned = status.strip().lower()
    if cleaned not in allowed:
        raise ValueError(f"Invalid {field_name}")
    return cleaned


def _apply_order_status_transition(
    session: Session,
    user: User,
    order: Order,
    next_status: str,
) -> None:
    current_status = order.status
    if next_status not in ORDER_STATUS_TRANSITIONS.get(current_status, set()):
        raise InvalidOrderTransitionError(
            f"Order status cannot transition from {current_status} to {next_status}"
        )
    if next_status == current_status:
        return
    if next_status == "cancelled" and _has_active_shipments(order):
        raise ShippingDestinationLockedError(
            "Order cannot be cancelled while active Shipments exist"
        )
    _add_order_event(
        session,
        user,
        order,
        OrderEventType.ORDER_CONFIRMED
        if next_status == "confirmed"
        else OrderEventType.ORDER_CANCELLED,
        from_value=current_status,
        to_value=next_status,
    )
    if next_status == "confirmed":
        consume_order_inventory(session, user, order)
    elif next_status == "cancelled" and current_status == "confirmed":
        restore_order_inventory(session, user, order)
    order.status = next_status
    if next_status == "cancelled" and order.cancelled_at is None:
        order.cancelled_at = datetime.now(UTC)


def _add_order_event(
    session: Session,
    user: User,
    order: Order,
    event_type: OrderEventType,
    *,
    from_value: str | None = None,
    to_value: str | None = None,
) -> None:
    session.add(
        OrderEvent(
            public_id=uuid4(),
            order_id=order.id,
            event_type=event_type.value,
            from_value=from_value,
            to_value=to_value,
            created_by_id=user.id,
            created_at=datetime.now(UTC),
        )
    )


def calculate_order_totals(
    items: Sequence[Mapping[str, object]],
    *,
    discount_amount: Decimal | int | float | str = Decimal("0"),
    shipping_fee: Decimal | int | float | str = Decimal("0"),
) -> OrderTotals:
    line_totals: list[Decimal] = []
    subtotal = Decimal("0")

    for item in items:
        quantity = int(item["quantity"])
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0")

        unit_price = _money(item["unit_price"])
        if unit_price < 0:
            raise ValueError("unit_price must not be negative")

        line_total = (Decimal(quantity) * unit_price).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        if line_total > MAX_MONEY:
            raise ValueError("line_total exceeds Numeric(12, 2) capacity")
        line_totals.append(line_total)
        subtotal += line_total
        if subtotal > MAX_MONEY:
            raise ValueError("subtotal_amount exceeds Numeric(12, 2) capacity")

    discount = _money(discount_amount)
    if discount < 0:
        raise ValueError("discount_amount must not be negative")
    shipping = _money(shipping_fee)
    if shipping < 0:
        raise ValueError("shipping_fee must not be negative")

    total = (subtotal - discount + shipping).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if total < 0:
        raise ValueError("total_amount cannot be negative")
    if total > MAX_MONEY:
        raise ValueError("total_amount exceeds Numeric(12, 2) capacity")

    return OrderTotals(
        subtotal_amount=subtotal.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        total_amount=total,
        line_totals=line_totals,
    )


def _prepare_order_items(
    session: Session,
    page,
    items: Sequence[Mapping[str, object]],
    *,
    currency: str,
) -> list[dict[str, object]]:
    prepared_items: list[dict[str, object]] = []
    for item in items:
        product_uuid = item.get("product_uuid")
        if product_uuid:
            product = resolve_product_for_order_item(session, page, str(product_uuid))
            if product.currency != currency:
                raise ValueError("Product currency must match order currency")
            prepared_items.append(
                {
                    **item,
                    "product_id": product.id,
                    "item_name": product.name,
                    "sku": product.sku,
                    "unit_price": product.sale_price if item.get("unit_price") is None else item["unit_price"],
                }
            )
            continue

        if item.get("item_name") is None:
            raise ValueError("item_name is required for manual items")
        if item.get("unit_price") is None:
            raise ValueError("unit_price is required for manual items")
        prepared_items.append({**item, "product_id": None})
    return prepared_items


def generate_order_number(_page_id: str, order_uuid: UUID) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"ORD-{today}-{order_uuid.hex[:12].upper()}"


def build_order_operational_queue_predicate(queue: OrderOperationalQueue):
    predicates = {
        OrderOperationalQueue.DRAFT: Order.status == "draft",
        OrderOperationalQueue.NEEDS_PAYMENT: and_(
            Order.status == "confirmed",
            Order.payment_status.in_(("unpaid", "partial")),
        ),
        OrderOperationalQueue.NEEDS_PACKING: and_(
            Order.status == "confirmed",
            Order.shipping_status == "pending",
        ),
        OrderOperationalQueue.PACKED: and_(
            Order.status == "confirmed",
            Order.shipping_status == "packed",
        ),
        OrderOperationalQueue.IN_TRANSIT: and_(
            Order.status == "confirmed",
            Order.shipping_status == "shipped",
        ),
        OrderOperationalQueue.SHIPPING_ISSUE: and_(
            Order.status == "confirmed",
            Order.shipping_status == "cancelled",
        ),
        OrderOperationalQueue.CANCELLED: Order.status == "cancelled",
    }
    return predicates[queue]


def list_orders(
    session: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    customer_id: int | None = None,
    queue: OrderOperationalQueue | None = None,
    status: str | None = None,
    payment_status: str | None = None,
    shipping_status: str | None = None,
    q: str | None = None,
) -> PaginatedResult[OrderListRecord] | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    page_size = min(page_size, 100)
    page = max(page, 1)

    query = (
        session.query(Order)
        .outerjoin(Customer, Customer.id == Order.customer_id)
        .outerjoin(Conversation, Conversation.id == Order.conversation_id)
        .filter(
            Order.facebook_page_id == page_obj.id,
            Order.deleted_at.is_(None),
            _order_conversation_is_page_consistent(page_obj.id),
        )
    )
    if customer_id is not None:
        query = query.filter(Order.customer_id == customer_id)
    if queue is not None:
        query = query.filter(build_order_operational_queue_predicate(queue))
    if status:
        query = query.filter(Order.status == _validate_status(status, ORDER_STATUSES, "status"))
    if payment_status:
        query = query.filter(
            Order.payment_status
            == _validate_status(payment_status, PAYMENT_STATUSES, "payment status")
        )
    if shipping_status:
        query = query.filter(
            Order.shipping_status
            == _validate_status(shipping_status, SHIPPING_STATUSES, "shipping status")
        )
    if q and q.strip():
        search = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                Order.order_number.ilike(search),
                Customer.name.ilike(search),
                Order.customer_name_snapshot.ilike(search),
                Order.customer_phone_snapshot.ilike(search),
                Order.customer_email_snapshot.ilike(search),
                Order.shipping_address.ilike(search),
                Order.note.ilike(search),
            )
        )

    total = query.count()
    item_count = (
        session.query(func.count(OrderItem.id))
        .filter(OrderItem.order_id == Order.id)
        .correlate(Order)
        .scalar_subquery()
    )
    ordering = (
        (Order.cancelled_at.desc(), Order.id.desc())
        if queue == OrderOperationalQueue.CANCELLED
        else (Order.created_at.desc(), Order.id.desc())
    )
    rows = (
        query.options(
            noload(Order.items),
            noload(Order.customer),
            noload(Order.conversation),
            noload(Order.shipments),
        )
        .add_columns(
            item_count.label("item_count"),
            Customer.public_id.label("customer_uuid"),
            Customer.name.label("customer_name"),
            Conversation.uuid.label("conversation_uuid"),
        )
        .order_by(*ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        OrderListRecord(
            order=order,
            item_count=int(count or 0),
            customer_uuid=customer_uuid,
            customer_name=customer_name,
            conversation_uuid=conversation_uuid,
        )
        for order, count, customer_uuid, customer_name, conversation_uuid in rows
    ]
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def get_order_operational_summary(
    session: Session,
    user: User,
) -> OrderOperationalSummary | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    queue_predicates = {
        queue: build_order_operational_queue_predicate(queue)
        for queue in OrderOperationalQueue
    }
    row = (
        session.query(
            func.count(Order.id),
            *[
                func.coalesce(func.sum(case((predicate, 1), else_=0)), 0)
                for predicate in queue_predicates.values()
            ],
        )
        .filter(
            Order.facebook_page_id == page_obj.id,
            Order.deleted_at.is_(None),
            _order_conversation_is_page_consistent(page_obj.id),
        )
        .one()
    )
    counts = [int(value or 0) for value in row]
    return OrderOperationalSummary(
        all=counts[0],
        **{
            queue.value: counts[index]
            for index, queue in enumerate(queue_predicates, start=1)
        },
    )


def get_order(session: Session, user: User, order_uuid: str) -> Order | None:
    return _resolve_order_for_page(session, user, order_uuid)


def _order_for_idempotency_key(
    session: Session,
    *,
    page_id: int,
    user_id: int,
    idempotency_key: str,
) -> Order | None:
    return (
        session.query(Order)
        .filter(
            Order.facebook_page_id == page_id,
            Order.created_by_id == user_id,
            Order.idempotency_key == idempotency_key,
        )
        .first()
    )


def _replay_or_conflict(order: Order, request_fingerprint: str) -> Order:
    if order.request_fingerprint != request_fingerprint:
        raise OrderIdempotencyConflictError(IDEMPOTENCY_CONFLICT_MESSAGE)
    return order


def _is_idempotency_unique_violation(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    return (
        IDEMPOTENCY_CONSTRAINT_NAME.lower() in message
        or (
            "unique constraint failed" in message
            and "orders.facebook_page_id" in message
            and "orders.created_by_id" in message
            and "orders.idempotency_key" in message
        )
    )


def _create_order_impl(
    session: Session,
    user: User,
    *,
    customer_uuid: str,
    conversation_uuid: str | None,
    items: Sequence[Mapping[str, object]],
    status: str = "draft",
    payment_status: str = "unpaid",
    shipping_status: str = "pending",
    currency: str = "VND",
    discount_amount: Decimal | int | float | str = Decimal("0"),
    shipping_fee: Decimal | int | float | str = Decimal("0"),
    shipping_address: str | None = None,
    shipping_destination: Mapping[str, object] | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    request_fingerprint: str | None = None,
) -> Order | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    if idempotency_key is not None:
        if request_fingerprint is None:
            raise ValueError("request_fingerprint is required with an idempotency key")
        existing_order = _order_for_idempotency_key(
            session,
            page_id=page_obj.id,
            user_id=user.id,
            idempotency_key=idempotency_key,
        )
        if existing_order is not None:
            return _replay_or_conflict(existing_order, request_fingerprint)

    customer = _resolve_customer_for_page(session, user, customer_uuid)
    if customer is None:
        return None

    conversation: Conversation | None = None
    if conversation_uuid is not None:
        conversation = get_conversation_for_user(session, user, conversation_uuid)
        if conversation is None or conversation.facebook_page_id != page_obj.id:
            return None
        linked_customer_id = resolve_customer_for_conversation(session, conversation)
        if linked_customer_id != customer.id:
            return None

    order_currency = (currency or "VND").strip().upper() or "VND"
    prepared_items = _prepare_order_items(session, page_obj, items, currency=order_currency)
    totals = calculate_order_totals(
        prepared_items,
        discount_amount=discount_amount,
        shipping_fee=shipping_fee,
    )

    order_uuid = uuid4()
    requested_status = _validate_status(status, ORDER_STATUSES, "status")
    normalized_destination = _normalise_shipping_input(
        shipping_destination,
        legacy_address=shipping_address,
        customer=customer,
    )
    order = Order(
        public_id=order_uuid,
        facebook_page_id=page_obj.id,
        customer_id=customer.id,
        conversation_id=conversation.id if conversation is not None else None,
        order_number=generate_order_number(page_obj.page_id, order_uuid),
        status="draft",
        payment_status=_validate_status(payment_status, PAYMENT_STATUSES, "payment_status"),
        shipping_status=_validate_status(shipping_status, SHIPPING_STATUSES, "shipping_status"),
        currency=order_currency,
        subtotal_amount=totals.subtotal_amount,
        discount_amount=_money(discount_amount),
        shipping_fee=_money(shipping_fee),
        total_amount=totals.total_amount,
        customer_name_snapshot=customer.name,
        customer_phone_snapshot=customer.phone,
        customer_email_snapshot=customer.email,
        note=_normalise_text(note),
        created_by_id=user.id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
    )
    _apply_shipping_destination(order, normalized_destination)
    session.add(order)
    session.flush()

    order_items: list[OrderItem] = []
    for item, line_total in zip(prepared_items, totals.line_totals, strict=True):
        order_item = OrderItem(
            public_id=uuid4(),
            order_id=order.id,
            product_id=item["product_id"],  # type: ignore[arg-type]
            item_name=str(item["item_name"]).strip(),
            sku=_normalise_text(item.get("sku")),
            quantity=int(item["quantity"]),
            unit_price=_money(item["unit_price"]),
            line_total=line_total,
            note=_normalise_text(item.get("note")),
        )
        if not order_item.item_name:
            raise ValueError("item_name must not be empty")
        order_items.append(order_item)

    session.add_all(order_items)
    order.items = order_items
    session.flush()
    _add_order_event(session, user, order, OrderEventType.ORDER_CREATED)
    _apply_order_status_transition(session, user, order, requested_status)
    session.commit()
    session.refresh(order)
    return order


def create_order(
    session: Session,
    user: User,
    *,
    customer_uuid: str,
    conversation_uuid: str | None,
    items: Sequence[Mapping[str, object]],
    status: str = "draft",
    payment_status: str = "unpaid",
    shipping_status: str = "pending",
    currency: str = "VND",
    discount_amount: Decimal | int | float | str = Decimal("0"),
    shipping_fee: Decimal | int | float | str = Decimal("0"),
    shipping_address: str | None = None,
    shipping_destination: Mapping[str, object] | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> Order | None:
    normalized_key = normalize_order_idempotency_key(idempotency_key)
    request_fingerprint = (
        build_order_create_fingerprint(
            customer_uuid=customer_uuid,
            conversation_uuid=conversation_uuid,
            items=items,
            status=status,
            payment_status=payment_status,
            shipping_status=shipping_status,
            currency=currency,
            discount_amount=discount_amount,
            shipping_fee=shipping_fee,
            shipping_address=shipping_address,
            shipping_destination=shipping_destination,
            note=note,
        )
        if normalized_key is not None
        else None
    )
    try:
        return _create_order_impl(
            session,
            user,
            customer_uuid=customer_uuid,
            conversation_uuid=conversation_uuid,
            items=items,
            status=status,
            payment_status=payment_status,
            shipping_status=shipping_status,
            currency=currency,
            discount_amount=discount_amount,
            shipping_fee=shipping_fee,
            shipping_address=shipping_address,
            shipping_destination=shipping_destination,
            note=note,
            idempotency_key=normalized_key,
            request_fingerprint=request_fingerprint,
        )
    except IntegrityError as exc:
        session.rollback()
        if normalized_key is None or not _is_idempotency_unique_violation(exc):
            raise
        page_obj = _current_page(session, user)
        if page_obj is None:
            return None
        winner = _order_for_idempotency_key(
            session,
            page_id=page_obj.id,
            user_id=user.id,
            idempotency_key=normalized_key,
        )
        if winner is None:
            raise
        return _replay_or_conflict(winner, request_fingerprint or "")
    except Exception:
        session.rollback()
        raise


def _update_order_impl(
    session: Session,
    user: User,
    order_uuid: str,
    *,
    data: Mapping[str, object],
) -> Order | None:
    order = _resolve_order_for_page(session, user, order_uuid, lock=True)
    if order is None:
        return None

    if "status" in data and data["status"] is not None:
        next_status = _validate_status(str(data["status"]), ORDER_STATUSES, "status")
        _apply_order_status_transition(session, user, order, next_status)
    if "payment_status" in data and data["payment_status"] is not None:
        next_payment_status = _validate_status(
            str(data["payment_status"]), PAYMENT_STATUSES, "payment_status"
        )
        if next_payment_status != order.payment_status:
            _add_order_event(
                session,
                user,
                order,
                OrderEventType.PAYMENT_STATUS_CHANGED,
                from_value=order.payment_status,
                to_value=next_payment_status,
            )
            order.payment_status = next_payment_status
    if "shipping_status" in data and data["shipping_status"] is not None:
        if _has_shipments(order):
            raise ShippingDestinationLockedError(
                "Order shipping_status is derived from Shipments once a Shipment exists"
            )
        next_shipping_status = _validate_status(
            str(data["shipping_status"]), SHIPPING_STATUSES, "shipping_status"
        )
        if next_shipping_status != order.shipping_status:
            _add_order_event(
                session,
                user,
                order,
                OrderEventType.SHIPPING_STATUS_CHANGED,
                from_value=order.shipping_status,
                to_value=next_shipping_status,
            )
            order.shipping_status = next_shipping_status
    if "currency" in data and data["currency"] is not None:
        currency = str(data["currency"]).strip().upper()
        if not currency:
            raise ValueError("currency must not be empty")
        order.currency = currency
    if "shipping_address" in data:
        if _shipping_destination_is_locked(order):
            raise ShippingDestinationLockedError(
                "Shipping destination cannot be edited after dispatch or cancellation"
            )
        order.shipping_address = _normalise_text(data["shipping_address"])  # type: ignore[arg-type]
        if order.shipping_address is not None and order.shipping_country_code is None:
            order.shipping_country_code = "VN"
    if "note" in data:
        order.note = _normalise_text(data["note"])  # type: ignore[arg-type]
    if "discount_amount" in data and data["discount_amount"] is not None:
        order.discount_amount = _money(data["discount_amount"])
    if "shipping_fee" in data and data["shipping_fee"] is not None:
        order.shipping_fee = _money(data["shipping_fee"])

    subtotal = sum((item.line_total for item in order.items), Decimal("0"))
    if subtotal > MAX_MONEY:
        raise ValueError("subtotal_amount exceeds Numeric(12, 2) capacity")
    total = (subtotal - _money(order.discount_amount) + _money(order.shipping_fee)).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    if total < 0:
        raise ValueError("total_amount cannot be negative")
    if total > MAX_MONEY:
        raise ValueError("total_amount exceeds Numeric(12, 2) capacity")

    order.subtotal_amount = subtotal.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    order.total_amount = total
    order.updated_at = datetime.now(UTC)

    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def update_order(
    session: Session,
    user: User,
    order_uuid: str,
    *,
    data: Mapping[str, object],
) -> Order | None:
    try:
        return _update_order_impl(session, user, order_uuid, data=data)
    except Exception:
        session.rollback()
        raise


def update_order_shipping_destination(
    session: Session,
    user: User,
    order_uuid: str,
    *,
    destination: Mapping[str, object],
) -> Order | None:
    try:
        order = _resolve_order_for_page(session, user, order_uuid, lock=True)
        if order is None:
            return None
        if _shipping_destination_is_locked(order):
            raise ShippingDestinationLockedError(
                "Shipping destination cannot be edited after dispatch or cancellation"
            )

        normalized = _normalise_shipping_input(destination)
        before = shipping_destination_for_order(order)
        _apply_shipping_destination(order, normalized)
        after = shipping_destination_for_order(order)
        if before == after:
            return order

        next_updated_at = datetime.now(UTC)
        current_updated_at = _utc(order.updated_at)
        if current_updated_at is not None:
            next_updated_at = max(
                next_updated_at,
                current_updated_at + timedelta(seconds=1),
            )
        order.updated_at = next_updated_at
        session.add(order)
        session.commit()
        session.refresh(order)
        return order
    except Exception:
        session.rollback()
        raise


def get_order_timeline(
    session: Session,
    user: User,
    order_uuid: str,
) -> list[OrderTimelineRecord] | None:
    """Return authoritative Order events and linked inventory movements chronologically."""
    order = _resolve_order_for_page(session, user, order_uuid, load_items=False)
    if order is None:
        return None

    event_rows = (
        session.query(OrderEvent, User.full_name, User.email)
        .outerjoin(User, OrderEvent.created_by_id == User.id)
        .filter(OrderEvent.order_id == order.id)
        .all()
    )
    movement_rows = (
        session.query(
            StockMovement,
            OrderItem.item_name,
            OrderItem.sku,
            User.full_name,
            User.email,
        )
        .join(OrderItem, StockMovement.order_item_id == OrderItem.id)
        .outerjoin(User, StockMovement.created_by_id == User.id)
        .filter(
            StockMovement.order_id == order.id,
            StockMovement.movement_type.in_(("ORDER_OUT", "ORDER_CANCEL_RESTORE")),
        )
        .all()
    )
    shipment_rows = (
        session.query(
            ShipmentEvent,
            Shipment.public_id,
            Shipment.shipment_number,
            User.full_name,
            User.email,
        )
        .join(Shipment, ShipmentEvent.shipment_id == Shipment.id)
        .outerjoin(User, ShipmentEvent.created_by_id == User.id)
        .filter(Shipment.order_id == order.id)
        .all()
    )

    timeline: list[OrderTimelineRecord] = [
        OrderEventTimelineRecord(
            public_id=event.public_id,
            event_type=event.event_type,
            from_value=event.from_value,
            to_value=event.to_value,
            actor_name=actor_name,
            actor_email=actor_email,
            created_at=event.created_at,
            sort_id=event.id,
        )
        for event, actor_name, actor_email in event_rows
    ]
    timeline.extend(
        InventoryMovementTimelineRecord(
            public_id=movement.public_id,
            movement_type=movement.movement_type,
            product_name=product_name,
            sku=sku,
            quantity_delta=movement.quantity_delta,
            quantity_before=movement.quantity_before,
            quantity_after=movement.quantity_after,
            actor_name=actor_name,
            actor_email=actor_email,
            created_at=movement.created_at,
            sort_id=movement.id,
        )
        for movement, product_name, sku, actor_name, actor_email in movement_rows
    )
    timeline.extend(
        ShipmentEventTimelineRecord(
            public_id=event.public_id,
            shipment_uuid=shipment_uuid,
            shipment_number=shipment_number,
            event_type=event.event_type,
            from_value=event.from_value,
            to_value=event.to_value,
            actor_name=actor_name,
            actor_email=actor_email,
            created_at=event.created_at,
            sort_id=event.id,
        )
        for event, shipment_uuid, shipment_number, actor_name, actor_email in shipment_rows
    )
    timeline.sort(
        key=lambda item: (
            _utc(item.created_at),
            0
            if isinstance(item, OrderEventTimelineRecord)
            else 1
            if isinstance(item, ShipmentEventTimelineRecord)
            else 2,
            item.sort_id,
        )
    )
    return timeline


def get_customer_orders(
    session: Session,
    user: User,
    customer_uuid: str,
    *,
    page: int = 1,
    page_size: int = 20,
    queue: OrderOperationalQueue | None = None,
    status: str | None = None,
    payment_status: str | None = None,
    shipping_status: str | None = None,
    q: str | None = None,
) -> PaginatedResult[OrderListRecord] | None:
    customer = _resolve_customer_for_page(session, user, customer_uuid)
    if customer is None:
        return None

    return list_orders(
        session,
        user,
        page=page,
        page_size=page_size,
        customer_id=customer.id,
        queue=queue,
        status=status,
        payment_status=payment_status,
        shipping_status=shipping_status,
        q=q,
    )


def get_customer_order_summary(
    session: Session,
    user: User,
    customer_uuid: str,
) -> CustomerOrderSummary | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    customer = _resolve_customer_for_page(session, user, customer_uuid)
    if customer is None:
        return None

    base_filters = (
        Order.facebook_page_id == page_obj.id,
        Order.customer_id == customer.id,
        Order.deleted_at.is_(None),
        _order_conversation_is_page_consistent(page_obj.id),
    )
    order_count, latest_order_at = (
        session.query(func.count(Order.id), func.max(Order.created_at))
        .filter(*base_filters)
        .one()
    )
    total_spend = (
        session.query(func.coalesce(func.sum(Order.total_amount), Decimal("0")))
        .filter(*base_filters, Order.status != "cancelled")
        .scalar()
    )

    return CustomerOrderSummary(
        order_count=int(order_count or 0),
        total_spend=_money(total_spend),
        latest_order_at=_utc(latest_order_at),
    )
