"""Carrier provider contracts without transport-specific operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class CarrierCapabilities:
    """Features a provider can support; M30.1 exposes metadata only."""

    supports_credentials: bool = False
    requires_credentials: bool = False
    shipment_binding: bool = True
    waybills: bool = False
    labels: bool = False
    tracking: bool = False
    rates: bool = False
    webhooks: bool = False


@dataclass(frozen=True)
class WaybillRecipient:
    name: str
    phone: str
    address_line: str
    ward: str
    district: str
    province: str
    postal_code: str | None
    country_code: str
    delivery_note: str | None


@dataclass(frozen=True)
class WaybillItem:
    name: str
    sku: str | None
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class CreateWaybillRequest:
    shipment_uuid: str
    shipment_number: str
    currency: str
    cod_amount: Decimal | None
    recipient: WaybillRecipient
    items: tuple[WaybillItem, ...]


@dataclass(frozen=True)
class CancelWaybillRequest:
    shipment_uuid: str
    external_id: str
    tracking_number: str | None


@dataclass(frozen=True)
class WaybillResult:
    external_id: str
    tracking_number: str | None
    tracking_url: str | None
    provider_created_at: datetime | None = None
    provider_updated_at: datetime | None = None


@dataclass(frozen=True)
class CarrierOperationError:
    code: str
    message: str
    retryable: bool = False
    outcome_unknown: bool = False


class CarrierOperationUnsupportedError(NotImplementedError):
    """Raised before persistence when a provider lacks an operation capability."""


@runtime_checkable
class CarrierProvider(Protocol):
    """Provider metadata and local credential validation contract."""

    code: str
    display_name: str
    capabilities: CarrierCapabilities

    def validate_credentials(self, credentials: Mapping[str, object]) -> None:
        """Validate credential shape locally without making network calls."""

    def validate_configuration(self, configuration: Mapping[str, object]) -> None:
        """Validate non-secret configuration locally without network calls."""

    def create_waybill(self, request: CreateWaybillRequest) -> WaybillResult:
        """Create a waybill; implemented only by providers advertising waybills."""

    def cancel_waybill(self, request: CancelWaybillRequest) -> WaybillResult:
        """Cancel a waybill; implemented only by providers advertising waybills."""
