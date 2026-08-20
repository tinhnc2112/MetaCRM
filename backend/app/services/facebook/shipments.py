"""Carrier-neutral Shipment services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.models.auth import User
from app.models.orders import Order
from app.models.shipments import Shipment, ShipmentEvent
from app.services.facebook.orders import (
    _order_conversation_is_page_consistent,
    _resolve_order_for_page,
    shipping_destination_for_order,
)
from app.services.facebook.pages import get_current_page
from sqlalchemy.orm import Session


SHIPMENT_STATUSES = {"ready", "packed", "shipped", "delivered", "cancelled"}
ACTIVE_SHIPMENT_STATUSES = {"ready", "packed", "shipped", "delivered"}
SHIPMENT_TRANSITIONS = {
    "ready": {"packed", "cancelled"},
    "packed": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


class ShipmentStateError(ValueError):
    """Raised when a Shipment or its Order is in an incompatible state."""


class ShipmentEventType(StrEnum):
    CREATED = "CREATED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ShipmentRecipientSnapshot:
    recipient_name: str
    recipient_phone: str
    recipient_phone_normalized: str
    address_line: str
    ward: str
    district: str
    province: str
    postal_code: str | None
    country_code: str
    delivery_note: str | None


def generate_shipment_number(order: Order, shipment_uuid: UUID) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"SHP-{today}-{order.public_id.hex[:6].upper()}-{shipment_uuid.hex[:8].upper()}"


def aggregate_order_shipping_status(shipments: list[Shipment]) -> str:
    if not shipments:
        return "pending"
    active = [shipment for shipment in shipments if shipment.status != "cancelled"]
    if not active:
        return "cancelled"
    active_statuses = {shipment.status for shipment in active}
    if active_statuses <= {"delivered"}:
        return "delivered"
    if active_statuses & {"shipped", "delivered"}:
        return "shipped"
    if "packed" in active_statuses:
        return "packed"
    return "pending"


def sync_order_shipping_status(order: Order) -> None:
    order.shipping_status = aggregate_order_shipping_status(list(order.shipments))
    order.updated_at = datetime.now(UTC)


def _snapshot_from_order(order: Order) -> ShipmentRecipientSnapshot:
    destination = shipping_destination_for_order(order)
    if destination is None or not destination.is_complete:
        raise ShipmentStateError("Order shipping destination is incomplete")
    if order.shipping_recipient_phone_normalized is None:
        raise ShipmentStateError("Order shipping destination is incomplete")
    return ShipmentRecipientSnapshot(
        recipient_name=destination.recipient_name or "",
        recipient_phone=destination.recipient_phone or "",
        recipient_phone_normalized=order.shipping_recipient_phone_normalized,
        address_line=destination.address_line or "",
        ward=destination.ward or "",
        district=destination.district or "",
        province=destination.province or "",
        postal_code=destination.postal_code,
        country_code=destination.country_code,
        delivery_note=destination.note,
    )


def _add_event(
    session: Session,
    user: User,
    shipment: Shipment,
    event_type: ShipmentEventType,
    *,
    from_value: str | None = None,
    to_value: str | None = None,
) -> None:
    session.add(
        ShipmentEvent(
            public_id=uuid4(),
            shipment_id=shipment.id,
            event_type=event_type.value,
            from_value=from_value,
            to_value=to_value,
            created_by_id=user.id,
            created_at=datetime.now(UTC),
        )
    )


def _resolve_shipment_for_page(
    session: Session,
    user: User,
    shipment_uuid: str,
    *,
    lock: bool = False,
) -> Shipment | None:
    try:
        public_id = UUID(shipment_uuid)
    except ValueError:
        return None

    page = get_current_page(session, user)
    if page is None:
        return None
    query = (
        session.query(Shipment)
        .join(Order, Shipment.order_id == Order.id)
        .filter(
            Shipment.public_id == public_id,
            Order.facebook_page_id == page.id,
            Order.deleted_at.is_(None),
            _order_conversation_is_page_consistent(page.id),
        )
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def create_shipment_for_order(
    session: Session,
    user: User,
    order_uuid: str,
) -> Shipment | None:
    try:
        order = _resolve_order_for_page(session, user, order_uuid, lock=True)
        if order is None:
            return None
        if order.status != "confirmed":
            raise ShipmentStateError("Shipment can only be created for confirmed Orders")
        snapshot = _snapshot_from_order(order)
        shipment_uuid = uuid4()
        shipment = Shipment(
            public_id=shipment_uuid,
            order_id=order.id,
            shipment_number=generate_shipment_number(order, shipment_uuid),
            status="ready",
            recipient_name=snapshot.recipient_name,
            recipient_phone=snapshot.recipient_phone,
            recipient_phone_normalized=snapshot.recipient_phone_normalized,
            address_line=snapshot.address_line,
            ward=snapshot.ward,
            district=snapshot.district,
            province=snapshot.province,
            postal_code=snapshot.postal_code,
            country_code=snapshot.country_code,
            delivery_note=snapshot.delivery_note,
            created_by_id=user.id,
            updated_by_id=user.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(shipment)
        session.flush()
        order.shipments.append(shipment)
        _add_event(session, user, shipment, ShipmentEventType.CREATED, to_value="ready")
        sync_order_shipping_status(order)
        session.add(order)
        session.commit()
        session.refresh(shipment)
        return shipment
    except Exception:
        session.rollback()
        raise


def list_shipments_for_order(
    session: Session,
    user: User,
    order_uuid: str,
) -> list[Shipment] | None:
    order = _resolve_order_for_page(session, user, order_uuid, load_items=False)
    if order is None:
        return None
    return (
        session.query(Shipment)
        .filter(Shipment.order_id == order.id)
        .order_by(Shipment.id)
        .all()
    )


def get_shipment(
    session: Session,
    user: User,
    shipment_uuid: str,
) -> Shipment | None:
    return _resolve_shipment_for_page(session, user, shipment_uuid)


def update_shipment_status(
    session: Session,
    user: User,
    shipment_uuid: str,
    status: str,
) -> Shipment | None:
    try:
        next_status = status.strip().lower()
        if next_status not in SHIPMENT_STATUSES:
            raise ValueError("Invalid shipment status")
        shipment = _resolve_shipment_for_page(session, user, shipment_uuid, lock=True)
        if shipment is None:
            return None
        order = shipment.order
        current_status = shipment.status
        if next_status == current_status:
            return shipment
        if next_status not in SHIPMENT_TRANSITIONS[current_status]:
            raise ShipmentStateError(
                f"Shipment status cannot transition from {current_status} to {next_status}"
            )

        now = datetime.now(UTC)
        shipment.status = next_status
        shipment.updated_by_id = user.id
        shipment.updated_at = now
        if next_status == "packed":
            shipment.packed_at = now
        elif next_status == "shipped":
            shipment.shipped_at = now
        elif next_status == "delivered":
            shipment.delivered_at = now
        elif next_status == "cancelled":
            shipment.cancelled_at = now

        _add_event(
            session,
            user,
            shipment,
            ShipmentEventType(next_status.upper()),
            from_value=current_status,
            to_value=next_status,
        )
        sync_order_shipping_status(order)
        session.add_all([shipment, order])
        session.commit()
        session.refresh(shipment)
        return shipment
    except Exception:
        session.rollback()
        raise
