"""Facebook Page-scoped product catalog models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.db.base import Base
from app.models.base import utc_now
from sqlalchemy import (
    Boolean,
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

if TYPE_CHECKING:
    from app.models.facebook import FacebookPage
    from app.models.orders import OrderItem


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("facebook_page_id", "sku", name="uq_products_page_sku"),
        Index("ix_products_facebook_page_id", "facebook_page_id"),
        Index("ix_products_name", "name"),
        Index("ix_products_sku", "sku"),
        Index("ix_products_is_active", "is_active"),
        Index("ix_products_deleted_at", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="VND")
    sale_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    page: Mapped[FacebookPage] = relationship()
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="product")
