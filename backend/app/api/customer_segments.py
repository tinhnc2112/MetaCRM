"""Customer segment management and preview endpoints."""

from __future__ import annotations

from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.customer_segments import (
    CustomerSegmentCustomersResponse,
    CustomerSegmentDeleteResponse,
    CustomerSegmentListResponse,
    CustomerSegmentPreviewResponse,
    CustomerSegmentResponse,
    CustomerSegmentRuleResponse,
    CustomerSegmentUpsertRequest,
)
from app.schemas.customers import CustomerProfileConversationResponse
from app.schemas.messenger import PaginationMeta
from app.services.facebook.conversations import unread_count_for_conversation
from app.services.facebook.customer_segments import (
    create_customer_segment,
    delete_customer_segment,
    get_customer_segment_for_user,
    list_customer_segment_customers,
    list_customer_segments,
    preview_customer_segment,
    preview_customer_segment_definition,
    update_customer_segment,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/segments", tags=["customer-segments"])


def _serialize_rule(rule) -> CustomerSegmentRuleResponse:
    return CustomerSegmentRuleResponse(
        id=rule.id,
        field=rule.field,
        operator=rule.operator,
        value=rule.value,
        sort_order=rule.sort_order,
    )


def _serialize_segment(segment) -> CustomerSegmentResponse:
    return CustomerSegmentResponse(
        id=segment.id,
        name=segment.name,
        description=segment.description,
        active=segment.active,
        created_by=segment.created_by,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
        customer_count=segment.customer_count,
        rules=[_serialize_rule(rule) for rule in segment.rules],
    )


def _serialize_customer(conversation, session: Session) -> CustomerProfileConversationResponse:
    return CustomerProfileConversationResponse(
        uuid=str(conversation.uuid),
        customer_psid=conversation.psid,
        customer_name=conversation.customer_name,
        customer_avatar_url=conversation.customer_avatar_url,
        last_message_at=conversation.last_message_at,
        unread_count=unread_count_for_conversation(session, conversation),
    )


def _serialize_customers(result, session: Session) -> CustomerSegmentCustomersResponse:
    return CustomerSegmentCustomersResponse(
        items=[_serialize_customer(conversation, session) for conversation in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )


def _serialize_preview(result, session: Session) -> CustomerSegmentPreviewResponse:
    payload = _serialize_customers(result, session)
    return CustomerSegmentPreviewResponse(items=payload.items, meta=payload.meta)


@router.get("", response_model=CustomerSegmentListResponse)
def list_segments_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerSegmentListResponse:
    segments = list_customer_segments(session, current_user)
    if segments is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")
    return CustomerSegmentListResponse(items=[_serialize_segment(segment) for segment in segments])


@router.post("/preview", response_model=CustomerSegmentPreviewResponse)
def preview_segment_definition_endpoint(
    payload: CustomerSegmentUpsertRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CustomerSegmentPreviewResponse:
    try:
        result = preview_customer_segment_definition(
            session,
            current_user,
            payload.name,
            payload.description,
            payload.active,
            payload.rules,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")
    return _serialize_preview(result, session)


@router.post("", response_model=CustomerSegmentResponse)
def create_segment_endpoint(
    payload: CustomerSegmentUpsertRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerSegmentResponse:
    try:
        segment = create_customer_segment(
            session,
            current_user,
            payload.name,
            payload.description,
            payload.active,
            payload.rules,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")
    return _serialize_segment(segment)


@router.get("/{segment_id}", response_model=CustomerSegmentResponse)
def get_segment_endpoint(
    segment_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerSegmentResponse:
    segment = get_customer_segment_for_user(session, current_user, segment_id)
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    preview = preview_customer_segment(session, current_user, segment_id)
    customer_count = preview.total if preview is not None else 0
    rules = [
        CustomerSegmentRuleResponse(
            id=rule.id,
            field=rule.field,
            operator=rule.operator,
            value=rule.value,
            sort_order=rule.sort_order,
        )
        for rule in segment.rules
    ]
    return CustomerSegmentResponse(
        id=segment.id,
        name=segment.name,
        description=segment.description,
        active=segment.active,
        created_by=segment.created_by,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
        customer_count=customer_count,
        rules=rules,
    )


@router.put("/{segment_id}", response_model=CustomerSegmentResponse)
def update_segment_endpoint(
    segment_id: int,
    payload: CustomerSegmentUpsertRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerSegmentResponse:
    try:
        segment = update_customer_segment(
            session,
            current_user,
            segment_id,
            payload.name,
            payload.description,
            payload.active,
            payload.rules,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return _serialize_segment(segment)


@router.delete("/{segment_id}", response_model=CustomerSegmentDeleteResponse)
def delete_segment_endpoint(
    segment_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerSegmentDeleteResponse:
    segment = delete_customer_segment(session, current_user, segment_id)
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return CustomerSegmentDeleteResponse(deleted=True, segment_id=segment.id)


@router.get("/{segment_id}/customers", response_model=CustomerSegmentCustomersResponse)
def list_segment_customers_endpoint(
    segment_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CustomerSegmentCustomersResponse:
    result = list_customer_segment_customers(session, current_user, segment_id, page=page, page_size=page_size)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return _serialize_customers(result, session)


@router.post("/{segment_id}/preview", response_model=CustomerSegmentPreviewResponse)
def preview_segment_endpoint(
    segment_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CustomerSegmentPreviewResponse:
    result = preview_customer_segment(session, current_user, segment_id, page=page, page_size=page_size)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return _serialize_preview(result, session)
