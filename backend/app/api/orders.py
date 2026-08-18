"""Customer-centric order endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.messenger import PaginationMeta
from app.schemas.orders import (
    OrderCreate,
    OrderItemResponse,
    OrderListItem,
    OrderListResponse,
    OrderResponse,
    OrderUpdate,
)
from app.services.facebook.orders import create_order, get_customer_orders, get_order, list_orders, update_order
from app.services.facebook.pages import get_current_page
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook", tags=["orders"])


def _money(value: object) -> str:
    return f"{Decimal(str(value)):.2f}"


def _serialize_item(item) -> OrderItemResponse:
    return OrderItemResponse(
        uuid=str(item.public_id),
        item_name=item.item_name,
        sku=item.sku,
        quantity=item.quantity,
        unit_price=_money(item.unit_price),
        line_total=_money(item.line_total),
        note=item.note,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _serialize_order(order) -> OrderResponse:
    return OrderResponse(
        uuid=str(order.public_id),
        order_number=order.order_number,
        customer_uuid=str(order.customer.public_id),
        customer_name_snapshot=order.customer_name_snapshot,
        customer_phone_snapshot=order.customer_phone_snapshot,
        customer_email_snapshot=order.customer_email_snapshot,
        conversation_uuid=str(order.conversation.uuid) if order.conversation is not None else None,
        status=order.status,
        payment_status=order.payment_status,
        shipping_status=order.shipping_status,
        currency=order.currency,
        subtotal_amount=_money(order.subtotal_amount),
        discount_amount=_money(order.discount_amount),
        shipping_fee=_money(order.shipping_fee),
        total_amount=_money(order.total_amount),
        shipping_address=order.shipping_address,
        note=order.note,
        created_at=order.created_at,
        updated_at=order.updated_at,
        cancelled_at=order.cancelled_at,
        items=[_serialize_item(item) for item in order.items],
        deleted_at=order.deleted_at,
    )


def _serialize_order_list_item(order) -> OrderListItem:
    return OrderListItem(
        uuid=str(order.public_id),
        order_number=order.order_number,
        customer_uuid=str(order.customer.public_id),
        customer_name_snapshot=order.customer_name_snapshot,
        customer_phone_snapshot=order.customer_phone_snapshot,
        customer_email_snapshot=order.customer_email_snapshot,
        conversation_uuid=str(order.conversation.uuid) if order.conversation is not None else None,
        status=order.status,
        payment_status=order.payment_status,
        shipping_status=order.shipping_status,
        currency=order.currency,
        subtotal_amount=_money(order.subtotal_amount),
        discount_amount=_money(order.discount_amount),
        shipping_fee=_money(order.shipping_fee),
        total_amount=_money(order.total_amount),
        shipping_address=order.shipping_address,
        note=order.note,
        created_at=order.created_at,
        updated_at=order.updated_at,
        cancelled_at=order.cancelled_at,
    )


@router.get("/orders", response_model=OrderListResponse)
def list_orders_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    customer_uuid: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OrderListResponse:
    if get_current_page(session, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")

    result = None
    if customer_uuid is not None:
        result = get_customer_orders(
            session,
            current_user,
            customer_uuid,
            page=page,
            page_size=page_size,
            status=status_filter,
            q=q,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    else:
        result = list_orders(
            session,
            current_user,
            page=page,
            page_size=page_size,
            status=status_filter,
            q=q,
        )

    return OrderListResponse(
        items=[_serialize_order_list_item(order) for order in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order_endpoint(
    order_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> OrderResponse:
    try:
        UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    order = get_order(session, current_user, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return _serialize_order(order)


@router.post("/orders", response_model=OrderResponse)
def create_order_endpoint(
    payload: OrderCreate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> OrderResponse:
    try:
        order = create_order(
            session,
            current_user,
            customer_uuid=payload.customer_uuid,
            conversation_uuid=payload.conversation_uuid,
            items=[item.model_dump() for item in payload.items],
            status=payload.status,
            payment_status=payload.payment_status,
            shipping_status=payload.shipping_status,
            currency=payload.currency,
            discount_amount=payload.discount_amount,
            shipping_fee=payload.shipping_fee,
            shipping_address=payload.shipping_address,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer or conversation not found")
    return _serialize_order(order)


@router.patch("/orders/{order_id}", response_model=OrderResponse)
def update_order_endpoint(
    order_id: str,
    payload: OrderUpdate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> OrderResponse:
    try:
        UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    try:
        order = update_order(session, current_user, order_id, data=payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return _serialize_order(order)


@router.get("/customers/{customer_uuid}/orders", response_model=OrderListResponse)
def customer_order_history_endpoint(
    customer_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OrderListResponse:
    if get_current_page(session, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")

    result = get_customer_orders(
        session,
        current_user,
        customer_uuid,
        page=page,
        page_size=page_size,
        status=status_filter,
        q=q,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    return OrderListResponse(
        items=[_serialize_order_list_item(order) for order in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )
