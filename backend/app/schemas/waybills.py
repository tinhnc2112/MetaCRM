"""Safe public schemas for external waybills and carrier operations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WaybillStatus = Literal["created", "cancelled", "unknown"]
CarrierOperationType = Literal["CREATE_WAYBILL", "CANCEL_WAYBILL"]
CarrierOperationStatus = Literal["pending", "succeeded", "failed", "unknown"]


class ExternalWaybillResponse(BaseModel):
    uuid: str
    shipment_uuid: str
    provider_code: str
    carrier_account_uuid: str
    carrier_account_display_name: str
    external_id: str
    tracking_number: str | None = None
    tracking_url: str | None = None
    status: WaybillStatus
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None = None


class ShipmentWaybillResponse(BaseModel):
    item: ExternalWaybillResponse | None = None


class CarrierOperationResponse(BaseModel):
    uuid: str
    shipment_uuid: str
    waybill_uuid: str | None = None
    provider_code: str
    carrier_account_uuid: str
    carrier_account_display_name: str
    operation_type: CarrierOperationType
    status: CarrierOperationStatus
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class CarrierOperationListResponse(BaseModel):
    items: list[CarrierOperationResponse]
