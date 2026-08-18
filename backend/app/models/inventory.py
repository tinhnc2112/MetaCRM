"""Page-scoped Product inventory persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.db.base import Base
from app.models.base import utc_now
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.orders import Order, OrderItem
    from app.models.products import Product


class ProductInventory(Base):
    __tablename__ = "product_inventories"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_product_inventories_public_id"),
        UniqueConstraint("product_id", name="uq_product_inventories_product_id"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_product_inventories_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_on_hand: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tracking_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    product: Mapped[Product] = relationship(back_populates="inventory")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_stock_movements_public_id"),
        UniqueConstraint("idempotency_key", name="uq_stock_movements_idempotency_key"),
        CheckConstraint(
            "movement_type IN ('OPENING', 'ADJUSTMENT', 'ORDER_OUT', 'ORDER_CANCEL_RESTORE')",
            name="ck_stock_movements_type",
        ),
        CheckConstraint(
            "quantity_delta <> 0 OR movement_type = 'OPENING'",
            name="ck_stock_movements_delta",
        ),
        CheckConstraint("quantity_before >= 0", name="ck_stock_movements_before_nonnegative"),
        CheckConstraint("quantity_after >= 0", name="ck_stock_movements_after_nonnegative"),
        Index("ix_stock_movements_product_created", "product_id", "created_at"),
        Index("ix_stock_movements_order_id", "order_id"),
        Index("ix_stock_movements_order_item_id", "order_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
    )
    order_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=True
    )
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    product: Mapped[Product] = relationship(back_populates="stock_movements")
    order: Mapped[Order | None] = relationship()
    order_item: Mapped[OrderItem | None] = relationship()
    created_by: Mapped[User | None] = relationship()
