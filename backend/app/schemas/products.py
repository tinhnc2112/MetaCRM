"""Schemas for the page-scoped Product catalog."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas.messenger import PaginationMeta
from pydantic import BaseModel, Field, field_validator

MAX_MONEY = Decimal("9999999999.99")


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ProductCreate(BaseModel):
    name: str = Field(max_length=255)
    sku: str | None = Field(default=None, max_length=255)
    currency: str = Field(default="VND", max_length=8)
    sale_price: Decimal = Field(ge=0, le=MAX_MONEY)
    description: str | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _required_text(value, "name")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return _required_text(value, "currency").upper()

    @field_validator("sku", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=255)
    currency: str | None = Field(default=None, max_length=8)
    sale_price: Decimal | None = Field(default=None, ge=0, le=MAX_MONEY)
    description: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name must not be null")
        return _required_text(value, "name")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("currency must not be null")
        return _required_text(value, "currency").upper()

    @field_validator("sale_price")
    @classmethod
    def validate_sale_price(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            raise ValueError("sale_price must not be null")
        return value

    @field_validator("is_active")
    @classmethod
    def validate_is_active(cls, value: bool | None) -> bool | None:
        if value is None:
            raise ValueError("is_active must not be null")
        return value

    @field_validator("sku", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)


class ProductListItem(BaseModel):
    uuid: str
    name: str
    sku: str | None = None
    currency: str
    sale_price: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductResponse(ProductListItem):
    pass


class ProductListResponse(BaseModel):
    items: list[ProductListItem]
    meta: PaginationMeta
