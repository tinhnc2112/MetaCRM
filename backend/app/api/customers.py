"""Messenger customer profile and internal note endpoints."""

from __future__ import annotations

from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.customers import (
    CustomerNoteCreateRequest,
    CustomerNoteDeleteResponse,
    CustomerNoteResponse,
    CustomerTagAssignmentResponse,
    CustomerTagSummaryResponse,
    CustomerNoteUpdateRequest,
    CustomerProfileConversationResponse,
    CustomerProfileResponse,
    CustomerTimelineResponse,
)
from app.schemas.customer_duplicates import (
    CustomerDuplicateCandidateResponse,
    CustomerDuplicateListResponse,
    CustomerMergeRequest,
    CustomerMergeResponse,
)
from app.services.facebook.customers import (
    create_customer_note,
    delete_customer_note,
    get_customer_profile,
    update_customer_note,
)
from app.services.facebook.customer_duplicates import list_customer_duplicates, merge_customers
from app.services.facebook.customer_tags import (
    assign_customer_tag_to_conversation,
    remove_customer_tag_from_conversation,
)
from app.services.facebook.conversations import unread_count_for_conversation
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.schemas.messenger import PaginationMeta

router = APIRouter(prefix="/facebook/customers", tags=["customers"])


def _serialize_conversation(conversation, session: Session) -> CustomerProfileConversationResponse:
    return CustomerProfileConversationResponse(
        uuid=str(conversation.uuid),
        customer_psid=conversation.psid,
        customer_name=conversation.customer_name,
        customer_avatar_url=conversation.customer_avatar_url,
        last_message_at=conversation.last_message_at,
        unread_count=unread_count_for_conversation(session, conversation),
    )


def _serialize_duplicate_candidate(candidate, session: Session) -> CustomerDuplicateCandidateResponse:
    return CustomerDuplicateCandidateResponse(
        primary_customer=_serialize_conversation(candidate.primary_customer, session),
        duplicate_customer=_serialize_conversation(candidate.duplicate_customer, session),
        confidence=candidate.confidence,
        reason=candidate.reason,
        matching_fields=candidate.matching_fields,
        matching_signals=candidate.matching_signals,
    )


def _serialize_profile(profile) -> CustomerProfileResponse:
    return CustomerProfileResponse(
        conversation=CustomerProfileConversationResponse(
            uuid=str(profile.conversation.uuid),
            customer_psid=profile.conversation.psid,
            customer_name=profile.conversation.customer_name,
            customer_avatar_url=profile.conversation.customer_avatar_url,
            last_message_at=profile.conversation.last_message_at,
            unread_count=profile.unread_count,
        ),
        tags=[
            CustomerTagSummaryResponse(
                id=tag.id,
                name=tag.name,
                slug=tag.slug,
                description=tag.description,
            )
            for tag in profile.tags
        ],
        timeline=[
            CustomerTimelineResponse(
                type=item.type,
                timestamp=item.timestamp,
                preview=item.preview,
                content=item.content,
                is_from_page=item.is_from_page,
                action=item.action,
                tag_name=item.tag_name,
                tag_slug=item.tag_slug,
            )
            for item in profile.timeline
        ],
        notes=[
            CustomerNoteResponse(
                id=str(note.uuid),
                content=note.content,
                created_at=note.created_at,
                updated_at=note.updated_at,
            )
            for note in profile.notes
        ],
    )


@router.get("/duplicates", response_model=CustomerDuplicateListResponse)
def list_customer_duplicates_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CustomerDuplicateListResponse:
    result = list_customer_duplicates(session, current_user, page=page, page_size=page_size)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook page is not selected")
    return CustomerDuplicateListResponse(
        items=[_serialize_duplicate_candidate(candidate, session) for candidate in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )


@router.post("/{primary_customer_id}/merge", response_model=CustomerMergeResponse)
def merge_customer_endpoint(
    primary_customer_id: str,
    payload: CustomerMergeRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerMergeResponse:
    try:
        result = merge_customers(session, current_user, primary_customer_id, payload.secondary_customer_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_409_CONFLICT if "already" in detail else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return CustomerMergeResponse(
        merge_id=result.merge.id,
        primary_customer=_serialize_conversation(result.primary_customer, session),
        secondary_customer=_serialize_conversation(result.secondary_customer, session),
        merged_by_user_id=result.merge.merged_by_user_id,
        merged_at=result.merge.created_at,
        duplicate_confidence=result.merge.duplicate_confidence,
        duplicate_reason=result.merge.duplicate_reason,
        matching_fields=result.merge.matching_fields,
        matching_signals=result.merge.matching_signals,
    )


def _serialize_note(note) -> CustomerNoteResponse:
    return CustomerNoteResponse(
        id=str(note.uuid),
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.get("/{conversation_id}", response_model=CustomerProfileResponse)
def customer_profile_endpoint(
    conversation_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerProfileResponse:
    profile = get_customer_profile(session, current_user, conversation_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return _serialize_profile(profile)


@router.post("/{conversation_id}/notes", response_model=CustomerNoteResponse)
def create_customer_note_endpoint(
    conversation_id: str,
    payload: CustomerNoteCreateRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerNoteResponse:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="content must not be empty")

    note = create_customer_note(session, current_user, conversation_id, content)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return _serialize_note(note)


@router.patch("/notes/{note_id}", response_model=CustomerNoteResponse)
def update_customer_note_endpoint(
    note_id: str,
    payload: CustomerNoteUpdateRequest,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerNoteResponse:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="content must not be empty")

    note = update_customer_note(session, current_user, note_id, content)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return _serialize_note(note)


@router.delete("/notes/{note_id}", response_model=CustomerNoteDeleteResponse)
def delete_customer_note_endpoint(
    note_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerNoteDeleteResponse:
    note = delete_customer_note(session, current_user, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return CustomerNoteDeleteResponse(deleted=True, note_id=str(note.uuid))


@router.get("/{conversation_id}/tags", response_model=list[CustomerTagSummaryResponse])
def customer_tags_endpoint(
    conversation_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[CustomerTagSummaryResponse]:
    profile = get_customer_profile(session, current_user, conversation_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return [
        CustomerTagSummaryResponse(
            id=tag.id,
            name=tag.name,
            slug=tag.slug,
            description=tag.description,
        )
        for tag in profile.tags
    ]


@router.post("/{conversation_id}/tags/{tag_id}", response_model=CustomerTagAssignmentResponse)
def assign_customer_tag_endpoint(
    conversation_id: str,
    tag_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerTagAssignmentResponse:
    result = assign_customer_tag_to_conversation(session, current_user, conversation_id, tag_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation or tag not found")
    return CustomerTagAssignmentResponse(
        customer_id=conversation_id,
        tag=CustomerTagSummaryResponse(
            id=result.tag.id,
            name=result.tag.name,
            slug=result.tag.slug,
            description=result.tag.description,
        ),
        attached=result.attached,
    )


@router.delete("/{conversation_id}/tags/{tag_id}", response_model=CustomerTagAssignmentResponse)
def remove_customer_tag_endpoint(
    conversation_id: str,
    tag_id: int,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CustomerTagAssignmentResponse:
    result = remove_customer_tag_from_conversation(session, current_user, conversation_id, tag_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation or tag not found")
    return CustomerTagAssignmentResponse(
        customer_id=conversation_id,
        tag=CustomerTagSummaryResponse(
            id=result.tag.id,
            name=result.tag.name,
            slug=result.tag.slug,
            description=result.tag.description,
        ),
        attached=result.attached,
    )
