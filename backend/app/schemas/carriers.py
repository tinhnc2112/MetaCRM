"""Schemas for carrier providers and Page-scoped accounts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CarrierAccountStatus = Literal["active", "inactive"]


class CarrierCapabilitiesResponse(BaseModel):
    supports_credentials: bool
    requires_credentials: bool
    shipment_binding: bool
    waybills: bool
    labels: bool
    tracking: bool
    rates: bool
    webhooks: bool


class CarrierProviderResponse(BaseModel):
    code: str
    display_name: str
    capabilities: CarrierCapabilitiesResponse


class CarrierProviderListResponse(BaseModel):
    items: list[CarrierProviderResponse]


class CarrierAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    credentials: dict[str, Any] | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_code", "display_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned


class CarrierAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    configuration: dict[str, Any] | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display_name must not be blank")
        return cleaned


class CarrierCredentialsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credentials: dict[str, Any]


class CarrierAccountResponse(BaseModel):
    uuid: str
    provider_code: str
    display_name: str
    status: CarrierAccountStatus
    configuration: dict[str, Any]
    configured: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None


class CarrierAccountListResponse(BaseModel):
    items: list[CarrierAccountResponse]
