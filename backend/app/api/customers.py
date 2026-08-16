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
    CustomerNoteUpdateRequest,
    CustomerProfileConversationResponse,
    CustomerProfileResponse,
    CustomerTimelineResponse,
)
from app.services.facebook.customers import (
    create_customer_note,
    delete_customer_note,
    get_customer_profile,
    update_customer_note,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/customers", tags=["customers"])


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
        timeline=[
            CustomerTimelineResponse(
                type=item.type,
                timestamp=item.timestamp,
                preview=item.preview,
                content=item.content,
                is_from_page=item.is_from_page,
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
