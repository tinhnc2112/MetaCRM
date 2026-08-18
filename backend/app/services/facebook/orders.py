"""Customer-centric order services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from uuid import UUID, uuid4

from app.models.auth import User
from app.models.customer_core import Customer
from app.models.messenger import Conversation
from app.models.orders import Order, OrderItem
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.conversations import PaginatedResult, get_conversation_for_user
from app.services.facebook.inventory import consume_order_inventory, restore_order_inventory
from app.services.facebook.pages import get_current_page
from app.services.facebook.products import resolve_product_for_order_item
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
class CustomerOrderSummary:
    order_count: int
    total_spend: Decimal
    latest_order_at: datetime | None


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
            "shipping_address": _normalise_text(shipping_address),
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
    session: Session, user: User, order_uuid: str, *, lock: bool = False
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
    if next_status == "confirmed":
        consume_order_inventory(session, user, order)
    elif next_status == "cancelled" and current_status == "confirmed":
        restore_order_inventory(session, user, order)
    order.status = next_status
    if next_status == "cancelled" and order.cancelled_at is None:
        order.cancelled_at = datetime.now(UTC)


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


def list_orders(
    session: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    customer_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
) -> PaginatedResult[Order] | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    page_size = min(page_size, 100)
    page = max(page, 1)

    query = session.query(Order).filter(
        Order.facebook_page_id == page_obj.id,
        Order.deleted_at.is_(None),
        _order_conversation_is_page_consistent(page_obj.id),
    )
    if customer_id is not None:
        query = query.filter(Order.customer_id == customer_id)
    if status:
        query = query.filter(Order.status == _validate_status(status, ORDER_STATUSES, "status"))
    if q and q.strip():
        search = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                Order.order_number.ilike(search),
                Order.customer_name_snapshot.ilike(search),
                Order.customer_phone_snapshot.ilike(search),
                Order.customer_email_snapshot.ilike(search),
                Order.shipping_address.ilike(search),
                Order.note.ilike(search),
            )
        )

    total = query.count()
    items = (
        query.order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


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
        shipping_address=_normalise_text(shipping_address) or customer.default_address,
        note=_normalise_text(note),
        created_by_id=user.id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
    )
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
        order.payment_status = _validate_status(
            str(data["payment_status"]), PAYMENT_STATUSES, "payment_status"
        )
    if "shipping_status" in data and data["shipping_status"] is not None:
        order.shipping_status = _validate_status(
            str(data["shipping_status"]), SHIPPING_STATUSES, "shipping_status"
        )
    if "currency" in data and data["currency"] is not None:
        currency = str(data["currency"]).strip().upper()
        if not currency:
            raise ValueError("currency must not be empty")
        order.currency = currency
    if "shipping_address" in data:
        order.shipping_address = _normalise_text(data["shipping_address"])  # type: ignore[arg-type]
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


def get_customer_orders(
    session: Session,
    user: User,
    customer_uuid: str,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    q: str | None = None,
) -> PaginatedResult[Order] | None:
    customer = _resolve_customer_for_page(session, user, customer_uuid)
    if customer is None:
        return None

    return list_orders(
        session,
        user,
        page=page,
        page_size=page_size,
        customer_id=customer.id,
        status=status,
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
