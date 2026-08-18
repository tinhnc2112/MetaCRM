"""API schemas for Page-scoped Product inventory."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.messenger import PaginationMeta
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_STOCK_QUANTITY = 9_223_372_036_854_775_807
MovementType = Literal["OPENING", "ADJUSTMENT", "ORDER_OUT", "ORDER_CANCEL_RESTORE"]


def _trimmed_note(value: str | None, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValueError("note is required")
        return None
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError("note is required")
    return cleaned or None


class InventoryEnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_quantity: int = Field(ge=0, le=MAX_STOCK_QUANTITY, strict=True)
    note: str | None = Field(default=None, max_length=5000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return _trimmed_note(value, required=False)


class InventoryAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity_delta: int = Field(
        ge=-MAX_STOCK_QUANTITY, le=MAX_STOCK_QUANTITY, strict=True
    )
    note: str = Field(min_length=1, max_length=5000)
    idempotency_key: UUID

    @field_validator("quantity_delta")
    @classmethod
    def validate_nonzero_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("quantity_delta must not be zero")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        return _trimmed_note(value, required=True) or ""


class InventoryResponse(BaseModel):
    product_uuid: str
    track_inventory: bool
    inventory_exists: bool
    quantity_on_hand: int | None = None
    tracking_started_at: datetime | None = None
    updated_at: datetime | None = None


class StockMovementResponse(BaseModel):
    uuid: str
    movement_type: MovementType
    quantity_delta: int
    quantity_before: int
    quantity_after: int
    note: str | None = None
    created_at: datetime


class StockMovementListResponse(BaseModel):
    items: list[StockMovementResponse]
    meta: PaginationMeta
