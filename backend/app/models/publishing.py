"""Durable Google Sheet publishing schedules and integration configuration."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.db.base import Base
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


def source_identity_key(source: str, spreadsheet_id: str, worksheet: str, external_id: str) -> str:
    payload = json.dumps([source, spreadsheet_id, worksheet, external_id], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SheetPublishingConfig(Base):
    __tablename__ = "sheet_publishing_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(255), nullable=False)
    worksheet: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(String(500))
    last_sync_result: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_scheduled_post_source_key"),
        CheckConstraint(
            "status IN ('INVALID','READY','SCHEDULED','PUBLISHING',"
            "'PUBLISHED','FAILED','UNCERTAIN','CANCELLED')",
            name="ck_scheduled_posts_status",
        ),
        Index("ix_scheduled_posts_due", "status", "scheduled_for_utc"),
        Index("ix_scheduled_posts_page", "facebook_page_id", "scheduled_for_utc"),
        Index("ix_scheduled_posts_writeback", "writeback_pending"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="google_sheet", nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    spreadsheet_id: Mapped[str] = mapped_column(String(255), nullable=False)
    worksheet: Mapped[str] = mapped_column(String(255), nullable=False)
    source_row: Mapped[int | None] = mapped_column(Integer)
    facebook_page_id: Mapped[int | None] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="RESTRICT")
    )
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_url: Mapped[str | None] = mapped_column(String(2048))
    scheduled_for_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    facebook_post_id: Mapped[str | None] = mapped_column(String(128))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    writeback_pending: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    writeback_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
