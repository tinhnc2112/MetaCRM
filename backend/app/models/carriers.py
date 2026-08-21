"""Page-scoped carrier account persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.db.base import Base
from app.models.base import utc_now
from sqlalchemy import (
    JSON,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
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
    external_waybills: Mapped[list[ExternalWaybill]] = relationship(
        back_populates="carrier_account", order_by="ExternalWaybill.id"
    )
    operations: Mapped[list[CarrierOperation]] = relationship(
        back_populates="carrier_account", order_by="CarrierOperation.id"
    )

    @property
    def configured(self) -> bool:
        """Report credential presence without exposing or decrypting credentials."""
        return bool(self.credentials_encrypted)


class ExternalWaybill(Base):
    """Provider-neutral external shipment identity; superseded rows remain historical."""

    __tablename__ = "external_waybills"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_external_waybills_public_id"),
        UniqueConstraint(
            "carrier_account_id", "external_id", name="uq_external_waybills_account_external_id"
        ),
        CheckConstraint(
            "status IN ('created', 'cancelled', 'unknown')", name="ck_external_waybills_status"
        ),
        Index("ix_external_waybills_page_created", "facebook_page_id", "created_at"),
        Index("ix_external_waybills_tracking", "provider_code", "tracking_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="RESTRICT"), nullable=False
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    carrier_account_id: Mapped[int] = mapped_column(
        ForeignKey("carrier_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    account_public_id_snapshot: Mapped[UUID] = mapped_column(nullable=False)
    account_display_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tracking_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tracking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="created")
    provider_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    page: Mapped[FacebookPage] = relationship()
    shipment: Mapped[Shipment] = relationship(
        back_populates="external_waybills", foreign_keys=[shipment_id]
    )
    carrier_account: Mapped[CarrierAccount] = relationship(back_populates="external_waybills")
    created_by: Mapped[User | None] = relationship()
    operations: Mapped[list[CarrierOperation]] = relationship(
        back_populates="waybill", order_by="CarrierOperation.id"
    )


class CarrierOperation(Base):
    """Durable, Page-scoped carrier command and idempotency record."""

    __tablename__ = "carrier_operations"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_carrier_operations_public_id"),
        UniqueConstraint(
            "facebook_page_id",
            "shipment_id",
            "carrier_account_id",
            "operation_type",
            "idempotency_key",
            name="uq_carrier_operations_scope_idempotency",
        ),
        CheckConstraint(
            "operation_type IN ('CREATE_WAYBILL', 'CANCEL_WAYBILL')",
            name="ck_carrier_operations_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'unknown')",
            name="ck_carrier_operations_status",
        ),
        Index("ix_carrier_operations_shipment_created", "shipment_id", "created_at", "id"),
        Index("ix_carrier_operations_page_created", "facebook_page_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    facebook_page_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_pages.id", ondelete="RESTRICT"), nullable=False
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    carrier_account_id: Mapped[int] = mapped_column(
        ForeignKey("carrier_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    external_waybill_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_waybills.id", ondelete="SET NULL"), nullable=True
    )
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    account_public_id_snapshot: Mapped[UUID] = mapped_column(nullable=False)
    account_display_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attempted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    page: Mapped[FacebookPage] = relationship()
    shipment: Mapped[Shipment] = relationship(back_populates="carrier_operations")
    carrier_account: Mapped[CarrierAccount] = relationship(back_populates="operations")
    waybill: Mapped[ExternalWaybill | None] = relationship(back_populates="operations")
    attempted_by: Mapped[User | None] = relationship()
