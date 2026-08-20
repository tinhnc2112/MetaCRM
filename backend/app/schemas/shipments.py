"""Pydantic schemas for carrier-neutral Shipments."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ShipmentStatus = Literal["ready", "packed", "shipped", "delivered", "cancelled"]


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
    tracking_number: str | None = None
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
