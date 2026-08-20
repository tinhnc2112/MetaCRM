"""Carrier provider contracts without transport-specific operations."""

from __future__ import annotations

from dataclasses import dataclass
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
