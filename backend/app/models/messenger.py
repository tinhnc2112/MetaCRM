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
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    psid: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notes: Mapped[list["CustomerNote"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )
    tag_assignments: Mapped[list["CustomerTagAssignment"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )
    tag_events: Mapped[list["CustomerTagEvent"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )
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
    mid: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_from_page: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    postback_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    fb_timestamp_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
