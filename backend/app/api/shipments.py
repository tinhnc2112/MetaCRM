"""Carrier-neutral Shipment endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.shipments import (
    ShipmentListResponse,
    ShipmentRecipientResponse,
    ShipmentResponse,
    ShipmentStatusUpdate,
    ShipmentTrackingUpdate,
)
from app.services.facebook.shipments import (
    ShipmentStateError,
    create_shipment_for_order,
    get_shipment,
    list_shipments_for_order,
    update_shipment_status,
    update_shipment_tracking,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook", tags=["shipments"])


def _validate_uuid(value: str, *, detail: str) -> None:
    try:
        UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc


def serialize_shipment(shipment) -> ShipmentResponse:
    def money(value) -> str | None:
        return None if value is None else str(value)

    return ShipmentResponse(
        uuid=str(shipment.public_id),
        order_uuid=str(shipment.order.public_id),
        shipment_number=shipment.shipment_number,
        status=shipment.status,
        recipient=ShipmentRecipientResponse(
            recipient_name=shipment.recipient_name,
            recipient_phone=shipment.recipient_phone,
            address_line=shipment.address_line,
            ward=shipment.ward,
            district=shipment.district,
            province=shipment.province,
            postal_code=shipment.postal_code,
            country_code=shipment.country_code,
            delivery_note=shipment.delivery_note,
        ),
        carrier_account_uuid=(
            str(shipment.carrier_account.public_id) if shipment.carrier_account else None
        ),
        carrier_provider_code=(
            shipment.carrier_account.provider_code if shipment.carrier_account else None
        ),
        carrier_account_display_name=(
            shipment.carrier_account.display_name if shipment.carrier_account else None
        ),
        carrier_code=shipment.carrier_code,
        carrier_name=shipment.carrier_name,
        tracking_number=shipment.tracking_number,
        tracking_url=shipment.tracking_url,
        shipping_fee=money(shipment.shipping_fee),
        cod_amount=money(shipment.cod_amount),
        note=shipment.note,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        packed_at=shipment.packed_at,
        shipped_at=shipment.shipped_at,
        delivered_at=shipment.delivered_at,
        cancelled_at=shipment.cancelled_at,
    )


@router.post("/orders/{order_id}/shipments", response_model=ShipmentResponse)
def create_order_shipment_endpoint(
    order_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ShipmentResponse:
    _validate_uuid(order_id, detail="Order not found")
    try:
        shipment = create_shipment_for_order(session, current_user, order_id)
    except ShipmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return serialize_shipment(shipment)


@router.get("/orders/{order_id}/shipments", response_model=ShipmentListResponse)
def list_order_shipments_endpoint(
    order_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ShipmentListResponse:
    _validate_uuid(order_id, detail="Order not found")
    shipments = list_shipments_for_order(session, current_user, order_id)
    if shipments is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return ShipmentListResponse(items=[serialize_shipment(shipment) for shipment in shipments])


@router.get("/shipments/{shipment_id}", response_model=ShipmentResponse)
def get_shipment_endpoint(
    shipment_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ShipmentResponse:
    _validate_uuid(shipment_id, detail="Shipment not found")
    shipment = get_shipment(session, current_user, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return serialize_shipment(shipment)


@router.patch("/shipments/{shipment_id}/status", response_model=ShipmentResponse)
def update_shipment_status_endpoint(
    shipment_id: str,
    payload: ShipmentStatusUpdate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ShipmentResponse:
    _validate_uuid(shipment_id, detail="Shipment not found")
    try:
        shipment = update_shipment_status(session, current_user, shipment_id, payload.status)
    except ShipmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return serialize_shipment(shipment)


@router.patch("/shipments/{shipment_id}/tracking", response_model=ShipmentResponse)
def update_shipment_tracking_endpoint(
    shipment_id: str,
    payload: ShipmentTrackingUpdate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ShipmentResponse:
    _validate_uuid(shipment_id, detail="Shipment not found")
    try:
        shipment = update_shipment_tracking(
            session,
            current_user,
            shipment_id,
            payload.model_dump(exclude_unset=True),
        )
    except ShipmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return serialize_shipment(shipment)
