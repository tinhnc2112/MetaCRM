"""In-process carrier provider registry."""

from __future__ import annotations

from app.carriers.base import CarrierProvider
from app.carriers.manual import manual_provider


class CarrierRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, CarrierProvider] = {}

    def register(self, provider: CarrierProvider) -> None:
        code = provider.code.strip().lower()
        if not code:
            raise ValueError("Carrier provider code is required")
        if code in self._providers:
            raise ValueError(f"Carrier provider already registered: {code}")
        self._providers[code] = provider

    def get(self, code: str) -> CarrierProvider | None:
        return self._providers.get(code.strip().lower())

    def list(self) -> tuple[CarrierProvider, ...]:
        return tuple(self._providers[code] for code in sorted(self._providers))


carrier_registry = CarrierRegistry()
carrier_registry.register(manual_provider)
