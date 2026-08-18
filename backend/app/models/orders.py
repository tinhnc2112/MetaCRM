"""Customer-centric order persistence models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.db.base import Base
from app.models.base import utc_now
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("facebook_page_id", "order_number", name="uq_orders_page_order_number"),
        Index("ix_orders_facebook_page_id", "facebook_page_id"),
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_order_number", "order_number"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_deleted_at", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("facebook_conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unpaid")
    shipping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="VND")
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    shipping_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    customer_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_email_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    page: Mapped["FacebookPage"] = relationship()
    customer: Mapped["Customer"] = relationship()
    conversation: Mapped["Conversation | None"] = relationship()
    creator: Mapped["User | None"] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderItem.id",
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_order_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship(back_populates="order_items", lazy="joined")
