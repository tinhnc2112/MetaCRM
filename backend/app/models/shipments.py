"""Carrier-neutral Shipment persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.db.base import Base
from app.models.base import utc_now
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.orders import Order


class Shipment(Base):
    """A concrete fulfillment execution for one Order."""

    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_shipments_public_id"),
        UniqueConstraint("shipment_number", name="uq_shipments_shipment_number"),
        CheckConstraint(
            "status IN ('ready', 'packed', 'shipped', 'delivered', 'cancelled')",
            name="ck_shipments_status",
        ),
        Index("ix_shipments_order_created", "order_id", "created_at"),
        Index("ix_shipments_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    shipment_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_phone_normalized: Mapped[str] = mapped_column(String(20), nullable=False)
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    ward: Mapped[str] = mapped_column(String(255), nullable=False)
    district: Mapped[str] = mapped_column(String(255), nullable=False)
    province: Mapped[str] = mapped_column(String(255), nullable=False)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="VN")
    delivery_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    carrier_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tracking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cod_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped[Order] = relationship(back_populates="shipments")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    events: Mapped[list[ShipmentEvent]] = relationship(
        back_populates="shipment", order_by="ShipmentEvent.id", lazy="selectin"
    )


class ShipmentEvent(Base):
    """Append-only record of an actual Shipment lifecycle action."""

    __tablename__ = "shipment_events"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_shipment_events_public_id"),
        CheckConstraint(
            "event_type IN ('CREATED', 'PACKED', 'SHIPPED', 'DELIVERED', "
            "'CANCELLED', 'TRACKING_UPDATED')",
            name="ck_shipment_events_type",
        ),
        Index("ix_shipment_events_shipment_created", "shipment_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_value: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    shipment: Mapped[Shipment] = relationship(back_populates="events")
    created_by: Mapped[User | None] = relationship()
