"""Page-scoped Product catalog endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.messenger import PaginationMeta
from app.schemas.products import (
    ProductCreate,
    ProductListItem,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services.facebook.products import (
    DuplicateProductSkuError,
    archive_product,
    create_product,
    get_product,
    list_products,
    update_product,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/products", tags=["products"])


def _money(value: object) -> str:
    return f"{Decimal(str(value)):.2f}"


def _serialize_product(product) -> ProductResponse:
    return ProductResponse(
        uuid=str(product.public_id),
        name=product.name,
        sku=product.sku,
        currency=product.currency,
        sale_price=_money(product.sale_price),
        description=product.description,
        is_active=product.is_active,
        track_inventory=product.track_inventory,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _serialize_product_list_item(product) -> ProductListItem:
    return ProductListItem(**_serialize_product(product).model_dump())


@router.get("", response_model=ProductListResponse)
def list_products_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    q: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    sku: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProductListResponse:
    result = list_products(
        session,
        current_user,
        page=page,
        page_size=page_size,
        q=q,
        active=active,
        sku=sku,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected"
        )
    return ProductListResponse(
        items=[_serialize_product_list_item(product) for product in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )


@router.get("/{product_uuid}", response_model=ProductResponse)
def get_product_endpoint(
    product_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProductResponse:
    product = get_product(session, current_user, product_uuid)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _serialize_product(product)


@router.post("", response_model=ProductResponse)
def create_product_endpoint(
    payload: ProductCreate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProductResponse:
    try:
        product = create_product(session, current_user, payload.model_dump())
    except DuplicateProductSkuError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected"
        )
    return _serialize_product(product)


@router.patch("/{product_uuid}", response_model=ProductResponse)
def update_product_endpoint(
    product_uuid: str,
    payload: ProductUpdate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProductResponse:
    try:
        product = update_product(
            session,
            current_user,
            product_uuid,
            payload.model_dump(exclude_unset=True),
        )
    except DuplicateProductSkuError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _serialize_product(product)


@router.delete("/{product_uuid}", response_model=ProductResponse)
def archive_product_endpoint(
    product_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProductResponse:
    product = archive_product(session, current_user, product_uuid)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _serialize_product(product)
