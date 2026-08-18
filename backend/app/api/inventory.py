"""Page-scoped Product inventory endpoints."""

from __future__ import annotations

from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.inventory import (
    InventoryAdjustmentRequest,
    InventoryEnableRequest,
    InventoryResponse,
    MovementType,
    StockMovementListResponse,
    StockMovementResponse,
)
from app.schemas.messenger import PaginationMeta
from app.services.facebook.inventory import (
    InsufficientInventoryError,
    InventoryIdempotencyConflictError,
    InventoryProductUnavailableError,
    InventoryStateError,
    adjust_product_inventory,
    disable_product_inventory,
    enable_product_inventory,
    get_product_inventory,
    list_inventory_movements,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/products/{product_uuid}/inventory", tags=["inventory"])


def _inventory_response(product, inventory) -> InventoryResponse:
    return InventoryResponse(
        product_uuid=str(product.public_id),
        track_inventory=product.track_inventory,
        inventory_exists=inventory is not None,
        quantity_on_hand=inventory.quantity_on_hand if inventory is not None else None,
        tracking_started_at=inventory.tracking_started_at if inventory is not None else None,
        updated_at=inventory.updated_at if inventory is not None else None,
    )


def _movement_response(movement) -> StockMovementResponse:
    return StockMovementResponse(
        uuid=str(movement.public_id),
        movement_type=movement.movement_type,
        quantity_delta=movement.quantity_delta,
        quantity_before=movement.quantity_before,
        quantity_after=movement.quantity_after,
        note=movement.note,
        created_at=movement.created_at,
    )


@router.get("", response_model=InventoryResponse)
def get_inventory_endpoint(
    product_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> InventoryResponse:
    result = get_product_inventory(session, current_user, product_uuid)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _inventory_response(*result)


@router.post("/enable", response_model=InventoryResponse)
def enable_inventory_endpoint(
    product_uuid: str,
    payload: InventoryEnableRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> InventoryResponse:
    try:
        result = enable_product_inventory(
            session,
            current_user,
            product_uuid,
            opening_quantity=payload.opening_quantity,
            note=payload.note,
        )
    except InventoryProductUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _inventory_response(*result)


@router.post("/disable", response_model=InventoryResponse)
def disable_inventory_endpoint(
    product_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> InventoryResponse:
    result = disable_product_inventory(session, current_user, product_uuid)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _inventory_response(*result)


@router.post("/adjustments", response_model=StockMovementResponse)
def adjust_inventory_endpoint(
    product_uuid: str,
    payload: InventoryAdjustmentRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> StockMovementResponse:
    try:
        movement = adjust_product_inventory(
            session,
            current_user,
            product_uuid,
            quantity_delta=payload.quantity_delta,
            note=payload.note,
            operation_id=payload.idempotency_key,
        )
    except InventoryProductUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        InventoryStateError,
        InsufficientInventoryError,
        InventoryIdempotencyConflictError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if movement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _movement_response(movement)


@router.get("/movements", response_model=StockMovementListResponse)
def list_movements_endpoint(
    product_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    movement_type: Annotated[MovementType | None, Query()] = None,
) -> StockMovementListResponse:
    result = list_inventory_movements(
        session,
        current_user,
        product_uuid,
        page=page,
        page_size=page_size,
        movement_type=movement_type,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return StockMovementListResponse(
        items=[_movement_response(item) for item in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )
