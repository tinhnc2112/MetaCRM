"""Facebook Messenger conversation and message persistence models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.db.base import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Conversation(Base):
    """A Messenger thread between a Facebook Page and one end-user (PSID)."""

    __tablename__ = "facebook_conversations"
    __table_args__ = (
        UniqueConstraint("page_id", "psid", name="uq_facebook_conversations_page_psid"),
        Index("ix_facebook_conversations_page_id", "page_id"),
        Index("ix_facebook_conversations_psid", "psid"),
        Index("ix_facebook_conversations_facebook_page_id", "facebook_page_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    # FK to facebook_pages (the Page that owns this conversation)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False
    )
    # page_id string — denormalised for fast lookup without joining facebook_pages
    page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # PSID — Page-scoped user ID of the end-user
    psid: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional display name retrieved from Graph API (nullable — not always available)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Timestamp of the most recent message — used for conversation ordering
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )


class Message(Base):
    """A single message within a Messenger conversation."""

    __tablename__ = "facebook_messages"
    __table_args__ = (
        UniqueConstraint("mid", name="uq_facebook_messages_mid"),
        Index("ix_facebook_messages_mid", "mid"),
        Index("ix_facebook_messages_conversation_id", "conversation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Facebook message ID — globally unique; used for idempotency
    mid: Mapped[str] = mapped_column(String(255), nullable=False)
    # "message" | "postback" | "read"
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Direction: True = sent from Page to customer, False = received from customer
    is_from_page: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Raw text content (nullable — attachments / postbacks may have no text)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Postback payload string (nullable)
    postback_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Facebook epoch timestamp in milliseconds from the webhook payload
    fb_timestamp_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Derived UTC datetime for easier querying
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
