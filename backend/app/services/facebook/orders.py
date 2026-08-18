"""Customer-centric order services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from app.models.auth import User
from app.models.customer_core import Customer
from app.models.messenger import Conversation
from app.models.orders import Order, OrderItem
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.conversations import PaginatedResult, get_conversation_for_user
from app.services.facebook.pages import get_current_page
from app.services.facebook.products import resolve_product_for_order_item
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

MONEY_QUANTUM = Decimal("0.01")
MAX_MONEY = Decimal("9999999999.99")
ORDER_STATUSES = {"draft", "confirmed", "cancelled"}
PAYMENT_STATUSES = {"unpaid", "partial", "paid", "refunded"}
SHIPPING_STATUSES = {"pending", "packed", "shipped", "delivered", "cancelled"}


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


def _resolve_order_for_page(session: Session, user: User, order_uuid: str) -> Order | None:
    page = _current_page(session, user)
    if page is None:
        return None
    try:
        public_id = UUID(order_uuid)
    except ValueError:
        return None
    return (
        session.query(Order)
        .filter(
            Order.public_id == public_id,
            Order.facebook_page_id == page.id,
            Order.deleted_at.is_(None),
            _order_conversation_is_page_consistent(page.id),
        )
        .first()
    )


def _validate_status(status: str, allowed: set[str], field_name: str) -> str:
    cleaned = status.strip().lower()
    if cleaned not in allowed:
        raise ValueError(f"Invalid {field_name}")
    return cleaned


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
) -> Order | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

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
    order = Order(
        public_id=order_uuid,
        facebook_page_id=page_obj.id,
        customer_id=customer.id,
        conversation_id=conversation.id if conversation is not None else None,
        order_number=generate_order_number(page_obj.page_id, order_uuid),
        status=_validate_status(status, ORDER_STATUSES, "status"),
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
    order = _resolve_order_for_page(session, user, order_uuid)
    if order is None:
        return None

    if "status" in data and data["status"] is not None:
        next_status = _validate_status(str(data["status"]), ORDER_STATUSES, "status")
        if order.status == "cancelled" and next_status != "cancelled":
            raise ValueError("cancelled orders cannot be reopened")
        order.status = next_status
        if next_status == "cancelled" and order.cancelled_at is None:
            order.cancelled_at = datetime.now(UTC)
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
