"""Page-scoped external waybill reads and carrier operation foundation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal

from app.carriers.base import CreateWaybillRequest, WaybillItem, WaybillRecipient
from app.carriers.registry import carrier_registry
from app.models.auth import User
from app.models.carriers import CarrierAccount, CarrierOperation, ExternalWaybill
from app.models.shipments import Shipment
from app.services.facebook.pages import get_current_page
from app.services.facebook.shipments import _resolve_shipment_for_page
from sqlalchemy.orm import Session


class CarrierOperationStateError(ValueError):
    pass


class CarrierIdempotencyConflictError(CarrierOperationStateError):
    pass


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def build_create_waybill_request(shipment: Shipment) -> CreateWaybillRequest:
    """Build the explicit provider payload only from immutable Shipment/Order snapshots."""
    order = shipment.order
    return CreateWaybillRequest(
        shipment_uuid=str(shipment.public_id),
        shipment_number=shipment.shipment_number,
        currency=order.currency,
        cod_amount=shipment.cod_amount,
        recipient=WaybillRecipient(
            name=shipment.recipient_name,
            phone=shipment.recipient_phone,
            address_line=shipment.address_line,
            ward=shipment.ward,
            district=shipment.district,
            province=shipment.province,
            postal_code=shipment.postal_code,
            country_code=shipment.country_code,
            delivery_note=shipment.delivery_note,
        ),
        items=tuple(
            WaybillItem(
                name=item.item_name,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            for item in order.items
        ),
    )


def safe_request_snapshot(request: CreateWaybillRequest) -> dict[str, object]:
    """Return the allow-listed business payload; credentials/configuration never enter it."""
    return _json_value(asdict(request))  # type: ignore[return-value]


def request_fingerprint(snapshot: dict[str, object]) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_current_waybill(
    session: Session, user: User, shipment_uuid: str
) -> tuple[Shipment, ExternalWaybill | None] | None:
    shipment = _resolve_shipment_for_page(session, user, shipment_uuid)
    if shipment is None:
        return None
    waybill = (
        session.query(ExternalWaybill)
        .filter(
            ExternalWaybill.id == shipment.current_external_waybill_id,
            ExternalWaybill.shipment_id == shipment.id,
            ExternalWaybill.facebook_page_id == shipment.order.facebook_page_id,
        )
        .first()
    )
    return shipment, waybill


def finalize_create_waybill(
    session: Session,
    operation_id: int,
    *,
    external_id: str,
    tracking_number: str | None = None,
    tracking_url: str | None = None,
    status: str = "created",
) -> ExternalWaybill:
    """Persist a provider result and assign the Shipment pointer in one locked transaction."""
    try:
        operation = (
            session.query(CarrierOperation)
            .filter(
                CarrierOperation.id == operation_id,
                CarrierOperation.operation_type == "CREATE_WAYBILL",
            )
            .with_for_update()
            .first()
        )
        if operation is None:
            raise CarrierOperationStateError("Create waybill operation not found")
        if operation.external_waybill_id is not None:
            waybill = session.get(ExternalWaybill, operation.external_waybill_id)
            if waybill is None:
                raise CarrierOperationStateError("Operation waybill no longer exists")
            return waybill

        shipment = (
            session.query(Shipment)
            .filter(Shipment.id == operation.shipment_id)
            .with_for_update()
            .first()
        )
        if shipment is None:
            raise CarrierOperationStateError("Shipment not found")
        current = (
            session.query(ExternalWaybill)
            .filter(
                ExternalWaybill.id == shipment.current_external_waybill_id,
                ExternalWaybill.shipment_id == shipment.id,
            )
            .first()
        )
        if current is not None and current.status != "cancelled":
            raise CarrierOperationStateError("Shipment already has a current waybill")
        if operation.facebook_page_id != current_page_id_for_shipment(session, shipment):
            raise CarrierOperationStateError("Operation is outside the Shipment Page")

        waybill = ExternalWaybill(
            facebook_page_id=operation.facebook_page_id,
            shipment_id=shipment.id,
            carrier_account_id=operation.carrier_account_id,
            provider_code=operation.provider_code,
            account_public_id_snapshot=operation.account_public_id_snapshot,
            account_display_name_snapshot=operation.account_display_name_snapshot,
            external_id=external_id,
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            status=status,
            created_by_id=operation.attempted_by_id,
        )
        session.add(waybill)
        session.flush()
        shipment.current_external_waybill_id = waybill.id
        operation.external_waybill_id = waybill.id
        operation.status = "succeeded"
        session.commit()
        session.refresh(waybill)
        return waybill
    except Exception:
        session.rollback()
        raise


def current_page_id_for_shipment(session: Session, shipment: Shipment) -> int:
    """Resolve Page ownership from the Shipment's Order without relationship state."""
    from app.models.orders import Order

    page_id = session.query(Order.facebook_page_id).filter(Order.id == shipment.order_id).scalar()
    if page_id is None:
        raise CarrierOperationStateError("Shipment Order not found")
    return page_id


def list_carrier_operations(
    session: Session, user: User, shipment_uuid: str
) -> tuple[Shipment, list[CarrierOperation]] | None:
    shipment = _resolve_shipment_for_page(session, user, shipment_uuid)
    if shipment is None:
        return None
    operations = (
        session.query(CarrierOperation)
        .filter(
            CarrierOperation.shipment_id == shipment.id,
            CarrierOperation.facebook_page_id == shipment.order.facebook_page_id,
        )
        .order_by(CarrierOperation.created_at.asc(), CarrierOperation.id.asc())
        .all()
    )
    return shipment, operations


def prepare_create_waybill_operation(
    session: Session,
    user: User,
    shipment_uuid: str,
    idempotency_key: str,
) -> tuple[CarrierOperation, bool] | None:
    """Validate and reserve an operation; callers invoke a real provider after commit.

    Unsupported providers are rejected before any record is inserted. This foundation
    intentionally performs no network call and does not mutate Shipment tracking/events.
    """
    key = idempotency_key.strip()
    if not key or len(key) > 128:
        raise ValueError("idempotency_key must contain 1 to 128 characters")
    try:
        shipment = _resolve_shipment_for_page(session, user, shipment_uuid, lock=True)
        if shipment is None:
            return None
        page = get_current_page(session, user)
        if page is None or not page.is_active:
            raise CarrierOperationStateError("Active Facebook Page is required")
        if shipment.status not in {"ready", "packed"}:
            raise CarrierOperationStateError("Shipment is not eligible for waybill creation")
        account = shipment.carrier_account
        if account is None:
            raise CarrierOperationStateError("Shipment has no carrier account")
        account = (
            session.query(CarrierAccount)
            .filter(CarrierAccount.id == account.id)
            .with_for_update()
            .first()
        )
        if account is None or account.facebook_page_id != page.id:
            raise CarrierOperationStateError("Carrier account is outside the current Page")
        if account.status != "active":
            raise CarrierOperationStateError("Carrier account is inactive")
        provider = carrier_registry.get(account.provider_code)
        if provider is None or not provider.capabilities.waybills:
            raise CarrierOperationStateError("Carrier provider does not support waybills")
        current = (
            session.query(ExternalWaybill)
            .filter(
                ExternalWaybill.id == shipment.current_external_waybill_id,
                ExternalWaybill.shipment_id == shipment.id,
            )
            .first()
        )
        if current is not None and current.status != "cancelled":
            raise CarrierOperationStateError("Shipment already has a current waybill")

        snapshot = safe_request_snapshot(build_create_waybill_request(shipment))
        fingerprint = request_fingerprint(snapshot)
        existing = (
            session.query(CarrierOperation)
            .filter(
                CarrierOperation.facebook_page_id == page.id,
                CarrierOperation.shipment_id == shipment.id,
                CarrierOperation.carrier_account_id == account.id,
                CarrierOperation.operation_type == "CREATE_WAYBILL",
                CarrierOperation.idempotency_key == key,
            )
            .with_for_update()
            .first()
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise CarrierIdempotencyConflictError(
                    "Idempotency key was already used with a different request"
                )
            return existing, True

        operation = CarrierOperation(
            facebook_page_id=page.id,
            shipment_id=shipment.id,
            carrier_account_id=account.id,
            provider_code=account.provider_code,
            account_public_id_snapshot=account.public_id,
            account_display_name_snapshot=account.display_name,
            operation_type="CREATE_WAYBILL",
            idempotency_key=key,
            request_fingerprint=fingerprint,
            status="pending",
            request_snapshot=snapshot,
            attempted_by_id=user.id,
        )
        session.add(operation)
        session.commit()
        session.refresh(operation)
        return operation, False
    except Exception:
        session.rollback()
        raise
