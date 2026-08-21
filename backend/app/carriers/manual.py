"""Built-in manual carrier provider."""

from __future__ import annotations

from collections.abc import Mapping

from app.carriers.base import (
    CancelWaybillRequest,
    CarrierCapabilities,
    CarrierOperationUnsupportedError,
    CreateWaybillRequest,
    WaybillResult,
)


class ManualCarrierProvider:
    code = "manual"
    display_name = "Manual"
    capabilities = CarrierCapabilities(
        supports_credentials=False,
        requires_credentials=False,
        shipment_binding=True,
    )

    def validate_credentials(self, credentials: Mapping[str, object]) -> None:
        if credentials:
            raise ValueError("Manual carrier accounts do not accept credentials")

    def validate_configuration(self, configuration: Mapping[str, object]) -> None:
        if not isinstance(configuration, Mapping):
            raise ValueError("configuration must be an object")

    def create_waybill(self, request: CreateWaybillRequest) -> WaybillResult:
        del request
        raise CarrierOperationUnsupportedError("Manual carrier does not support waybills")

    def cancel_waybill(self, request: CancelWaybillRequest) -> WaybillResult:
        del request
        raise CarrierOperationUnsupportedError("Manual carrier does not support waybills")


manual_provider = ManualCarrierProvider()
