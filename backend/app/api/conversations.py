"""Messenger CRM read API — conversations and messages."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.models.messenger import Conversation, Message
from app.schemas.messenger import (
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    MessageResponse,
    PaginationMeta,
)
from app.services.facebook.conversations import (
    get_conversation_for_user,
    list_conversations,
    list_messages,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/conversations", tags=["conversations"])

# Maximum page_size guard (also enforced in service layer, but validate early)
_MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialize_conversation(conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=str(conv.uuid),
        page_id=conv.page_id,
        psid=conv.psid,
        customer_name=conv.customer_name,
        last_message_at=conv.last_message_at,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _serialize_message(msg: Message, conversation_uuid: str) -> MessageResponse:
    return MessageResponse(
        id=str(msg.uuid),
        conversation_id=conversation_uuid,
        mid=msg.mid,
        event_type=msg.event_type,
        is_from_page=msg.is_from_page,
        text=msg.text,
        postback_payload=msg.postback_payload,
        fb_timestamp_ms=msg.fb_timestamp_ms,
        sent_at=msg.sent_at,
        created_at=msg.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/facebook/conversations
# ---------------------------------------------------------------------------


@router.get("", response_model=ConversationListResponse)
def list_conversations_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page_id: str | None = Query(default=None, description="Filter by Facebook page_id"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE, description="Items per page"),
) -> ConversationListResponse:
    """List conversations the current user has access to.

    Access is controlled by Facebook Page ownership: only conversations
    belonging to pages connected to the user's Facebook account are returned.
    Results are sorted newest-message-first.
    """
    result = list_conversations(
        session,
        current_user,
        page_id_filter=page_id,
        page=page,
        page_size=page_size,
    )

    return ConversationListResponse(
        items=[_serialize_conversation(conv) for conv in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/facebook/conversations/{conversation_id}/messages
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages_endpoint(
    conversation_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=50, ge=1, le=_MAX_PAGE_SIZE, description="Items per page"),
    oldest_first: bool = Query(default=False, description="Order messages oldest-first when True"),
) -> MessageListResponse:
    """Return messages in a conversation the user is authorised to access.

    ``conversation_id`` is the UUID of the conversation (not the integer PK).
    Returns 404 if the conversation does not exist or the user has no access.
    Default ordering is newest-first; pass ``oldest_first=true`` for
    chronological order.
    """
    # Validate that conversation_id is a valid UUID format
    try:
        UUID(conversation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    conversation = get_conversation_for_user(session, current_user, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    result = list_messages(
        session,
        conversation,
        page=page,
        page_size=page_size,
        oldest_first=oldest_first,
    )

    conv_uuid_str = str(conversation.uuid)
    return MessageListResponse(
        items=[_serialize_message(msg, conv_uuid_str) for msg in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )
