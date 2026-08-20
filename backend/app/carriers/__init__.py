"""Provider-neutral carrier integration primitives."""

from app.carriers.base import CarrierCapabilities, CarrierProvider
from app.carriers.registry import carrier_registry

__all__ = ["CarrierCapabilities", "CarrierProvider", "carrier_registry"]
