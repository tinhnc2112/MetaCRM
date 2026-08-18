"""Channel-independent Customer aggregate (M19 Customer Core).

A Customer represents one real end-user regardless of which channel
(Facebook Messenger today; Instagram/TikTok/Zalo later) they were first
seen on. CustomerIdentity maps a Page-scoped channel identity to a Customer
so channel-specific tables (Conversation, future Order, etc.) can reference
a stable customer_id instead of a channel-specific identifier.

See docs/02_DOMAIN_MODEL.md and docs/03_CUSTOMER.md for the source spec.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.db.base import Base
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.facebook import FacebookPage


def utc_now() -> datetime:
    return datetime.now(UTC)


class Customer(Base):
    """Channel-independent customer. One row per real end-user."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    default_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    # M19.5: set when this Customer has been merged into another Customer.
    # Self-referential, so ON DELETE SET NULL avoids a cascade cycle.
    merged_into_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    identities: Mapped[list[CustomerIdentity]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="CustomerIdentity.customer_id",
    )
    merged_into: Mapped[Customer | None] = relationship(
        remote_side="Customer.id", foreign_keys=[merged_into_customer_id]
    )


class CustomerIdentity(Base):
    """Maps one (channel, Facebook Page, external_id) tuple to a Customer.

    A customer may hold multiple identities (e.g. the same person messaging
    from two different Facebook Pages, or later, Instagram/Zalo). external_id
    is the channel's own user identifier (Facebook PSID today).
    """

    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint(
            "channel",
            "facebook_page_id",
            "external_id",
            name="uq_customer_identities_channel_page_external_id",
        ),
        Index("ix_customer_identities_customer_id", "customer_id"),
        Index("ix_customer_identities_facebook_page_id", "facebook_page_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    facebook_page_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "facebook_pages.id",
            name="fk_customer_identities_facebook_page_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    identity_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    customer: Mapped[Customer] = relationship(back_populates="identities")
    facebook_page: Mapped[FacebookPage] = relationship()
