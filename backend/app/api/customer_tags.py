"""Customer tag CRUD and filtering endpoints."""

from __future__ import annotations

from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.customers import (
    CustomerProfileConversationResponse,
    CustomerTagCreateRequest,
    CustomerTagCustomersResponse,
    CustomerTagDeleteResponse,
    CustomerTagListResponse,
    CustomerTagResponse,
    CustomerTagUpdateRequest,
)
from app.schemas.messenger import PaginationMeta
from app.services.facebook.conversations import unread_count_for_conversation
from app.services.facebook.customer_tags import (
    create_customer_tag,
    delete_customer_tag,
    list_customer_tag_customers,
    list_customer_tags,
    update_customer_tag,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/customer-tags", tags=["customer-tags"])


def _serialize_tag(tag) -> CustomerTagResponse:
    return CustomerTagResponse(
        id=tag.id,
        name=tag.name,
        slug=tag.slug,
        description=tag.description,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
        customer_count=tag.customer_count,
    )


@router.get("", response_model=CustomerTagListResponse)
def list_customer_tags_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerTagListResponse:
    tags = list_customer_tags(session, current_user)
    if tags is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")
    return CustomerTagListResponse(items=[_serialize_tag(tag) for tag in tags])


@router.post("", response_model=CustomerTagResponse)
def create_customer_tag_endpoint(
    payload: CustomerTagCreateRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerTagResponse:
    try:
        tag = create_customer_tag(session, current_user, payload.name, payload.description)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_409_CONFLICT if "already exists" in detail else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")
    return _serialize_tag(tag)


@router.patch("/{tag_id}", response_model=CustomerTagResponse)
def update_customer_tag_endpoint(
    tag_id: int,
    payload: CustomerTagUpdateRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerTagResponse:
    try:
        tag = update_customer_tag(session, current_user, tag_id, payload.name, payload.description)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_409_CONFLICT if "already exists" in detail else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return _serialize_tag(tag)


@router.delete("/{tag_id}", response_model=CustomerTagDeleteResponse)
def delete_customer_tag_endpoint(
    tag_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerTagDeleteResponse:
    tag = delete_customer_tag(session, current_user, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return CustomerTagDeleteResponse(deleted=True, tag_id=tag.id)


@router.get("/{tag_id}/customers", response_model=CustomerTagCustomersResponse)
def list_customer_tag_customers_endpoint(
    tag_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CustomerTagCustomersResponse:
    result = list_customer_tag_customers(session, current_user, tag_id, page=page, page_size=page_size)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return CustomerTagCustomersResponse(
        items=[
            CustomerProfileConversationResponse(
                uuid=str(conversation.uuid),
                customer_psid=conversation.psid,
                customer_name=conversation.customer_name,
                customer_avatar_url=conversation.customer_avatar_url,
                last_message_at=conversation.last_message_at,
                unread_count=unread_count_for_conversation(session, conversation),
            )
            for conversation in result.items
        ],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )
