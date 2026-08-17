"""Customer note models for Messenger CRM profiles."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.db.base import Base
from app.models.base import utc_now
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship


class CustomerNote(Base):
    __tablename__ = "customer_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[UUID] = mapped_column(unique=True, nullable=False, default=uuid4, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="notes")
    user: Mapped["User"] = relationship()


class CustomerTag(Base):
    __tablename__ = "customer_tags"
    __table_args__ = (
        UniqueConstraint("facebook_page_id", "name", name="uq_customer_tags_page_name"),
        UniqueConstraint("facebook_page_id", "slug", name="uq_customer_tags_page_slug"),
        Index("ix_customer_tags_facebook_page_id", "facebook_page_id"),
        Index("ix_customer_tags_slug", "slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    page: Mapped["FacebookPage"] = relationship()
    assignments: Mapped[list["CustomerTagAssignment"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list["CustomerTagEvent"]] = relationship(back_populates="tag", lazy="selectin")


class CustomerTagAssignment(Base):
    __tablename__ = "customer_tag_assignments"
    __table_args__ = (
        UniqueConstraint("conversation_id", "tag_id", name="uq_customer_tag_assignments_conversation_tag"),
        Index("ix_customer_tag_assignments_conversation_id", "conversation_id"),
        Index("ix_customer_tag_assignments_tag_id", "tag_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_conversations.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("customer_tags.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="tag_assignments")
    tag: Mapped["CustomerTag"] = relationship(back_populates="assignments")


class CustomerTagEvent(Base):
    __tablename__ = "customer_tag_events"
    __table_args__ = (
        Index("ix_customer_tag_events_conversation_id", "conversation_id"),
        Index("ix_customer_tag_events_tag_id", "tag_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_conversations.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_tags.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    tag_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    tag_slug_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="tag_events")
    tag: Mapped["CustomerTag"] = relationship(back_populates="events")
    user: Mapped["User"] = relationship()


class CustomerSegment(Base):
    __tablename__ = "customer_segments"
    __table_args__ = (
        Index("ix_customer_segments_facebook_page_id", "facebook_page_id"),
        Index("ix_customer_segments_active", "active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    page: Mapped["FacebookPage"] = relationship()
    creator: Mapped["User"] = relationship()
    rules: Mapped[list["CustomerSegmentRule"]] = relationship(
        back_populates="segment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CustomerSegmentRule.sort_order, CustomerSegmentRule.id",
    )


class CustomerSegmentRule(Base):
    __tablename__ = "customer_segment_rules"
    __table_args__ = (
        Index("ix_customer_segment_rules_segment_id", "segment_id"),
        Index("ix_customer_segment_rules_sort_order", "segment_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment_id: Mapped[int] = mapped_column(
        ForeignKey("customer_segments.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    segment: Mapped["CustomerSegment"] = relationship(back_populates="rules")
