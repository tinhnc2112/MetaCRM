"""Pydantic schemas for carrier-neutral Shipments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ShipmentStatus = Literal["ready", "packed", "shipped", "delivered", "cancelled"]
MAX_MONEY = Decimal("9999999999.99")


class ShipmentRecipientResponse(BaseModel):
    recipient_name: str
    recipient_phone: str
    address_line: str
    ward: str
    district: str
    province: str
    postal_code: str | None = None
    country_code: str
    delivery_note: str | None = None


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    order_uuid: str
    shipment_number: str
    status: ShipmentStatus
    recipient: ShipmentRecipientResponse
    carrier_account_uuid: str | None = None
    carrier_provider_code: str | None = None
    carrier_account_display_name: str | None = None
    carrier_code: str | None = None
    carrier_name: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    shipping_fee: str | None = None
    cod_amount: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    packed_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None


class ShipmentListResponse(BaseModel):
    items: list[ShipmentResponse]


class ShipmentStatusUpdate(BaseModel):
    status: ShipmentStatus


class ShipmentTrackingUpdate(BaseModel):
    carrier_code: str | None = Field(default=None, max_length=64)
    carrier_name: str | None = Field(default=None, max_length=255)
    tracking_number: str | None = Field(default=None, max_length=255)
    tracking_url: str | None = Field(default=None, max_length=5000)
    shipping_fee: Decimal | None = Field(default=None, ge=Decimal("0"), le=MAX_MONEY)
    cod_amount: Decimal | None = Field(default=None, ge=Decimal("0"), le=MAX_MONEY)
    note: str | None = Field(default=None, max_length=5000)

    @field_validator(
        "carrier_code",
        "carrier_name",
        "tracking_number",
        "tracking_url",
        "note",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("tracking_url")
    @classmethod
    def validate_tracking_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("tracking_url must start with http:// or https://")
        return value
