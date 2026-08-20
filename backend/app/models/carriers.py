"""Page-scoped carrier account persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.db.base import Base
from app.models.base import utc_now
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.facebook import FacebookPage
    from app.models.shipments import Shipment


class CarrierAccount(Base):
    __tablename__ = "carrier_accounts"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_carrier_accounts_public_id"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_carrier_accounts_status"),
        Index("ix_carrier_accounts_page_status", "facebook_page_id", "status"),
        Index("ix_carrier_accounts_page_provider", "facebook_page_id", "provider_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    page: Mapped[FacebookPage] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    deactivated_by: Mapped[User | None] = relationship(foreign_keys=[deactivated_by_id])
    shipments: Mapped[list[Shipment]] = relationship(back_populates="carrier_account")

    @property
    def configured(self) -> bool:
        """Report credential presence without exposing or decrypting credentials."""
        return bool(self.credentials_encrypted)
