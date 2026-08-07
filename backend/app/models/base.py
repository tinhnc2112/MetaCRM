"""Foundation mixins for future SQLAlchemy domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-managed fields."""
    return datetime.now(UTC)


class UUIDMixin:
    """Provide UUID primary keys without relying on a database-specific UUID type."""

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class UTCDateTimeMixin:
    """Provide creation and update timestamps generated in UTC."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class SoftDeleteMixin:
    """Represent deletion as a timestamp so records remain recoverable."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def soft_delete(self) -> None:
        self.deleted_at = utc_now()
        self.is_deleted = True

    def restore(self) -> None:
        self.deleted_at = None
        self.is_deleted = False


class AuditMixin:
    """Provide optional actor identifiers without imposing user-table foreign keys."""

    created_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, default=None)
    updated_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, default=None)


class BaseModel(UUIDMixin, UTCDateTimeMixin, SoftDeleteMixin, AuditMixin, Base):
    """Abstract common model base for future domain tables."""

    __abstract__ = True
