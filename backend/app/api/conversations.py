"""Messenger CRM read API - conversations and messages."""

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
    MarkConversationReadResponse,
    MessageListResponse,
    MessageResponse,
    PaginationMeta,
)
from app.services.facebook.conversations import (
    conversation_last_message_preview,
    get_conversation_for_user,
    list_conversations,
    list_messages,
    mark_conversation_read,
    unread_count_for_conversation,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook/conversations", tags=["conversations"])
_MAX_PAGE_SIZE = 100


def _serialize_conversation(session: Session, conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=str(conv.uuid),
        page_id=conv.page_id,
        psid=conv.psid,
        customer_name=conv.customer_name,
        last_message_at=conv.last_message_at,
        last_message_preview=conversation_last_message_preview(session, conv),
        unread_count=unread_count_for_conversation(session, conv),
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _serialize_message(msg: Message, conversation: Conversation) -> MessageResponse:
    return MessageResponse(
        id=str(msg.uuid),
        conversation_id=str(conversation.uuid),
        sender_psid=None if msg.is_from_page else conversation.psid,
        recipient_page_id=conversation.page_id,
        mid=msg.mid,
        event_type=msg.event_type,
        is_from_page=msg.is_from_page,
        text=msg.text,
        attachments=None,
        postback_payload=msg.postback_payload,
        fb_timestamp_ms=msg.fb_timestamp_ms,
        sent_at=msg.sent_at,
        created_at=msg.created_at,
    )


@router.get("", response_model=ConversationListResponse)
def list_conversations_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
) -> ConversationListResponse:
    result = list_conversations(session, current_user, page_id_filter=page_id, page=page, page_size=page_size)
    return ConversationListResponse(
        items=[_serialize_conversation(session, conv) for conv in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages_endpoint(
    conversation_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=_MAX_PAGE_SIZE),
    oldest_first: bool = Query(default=False),
) -> MessageListResponse:
    try:
        UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    conversation = get_conversation_for_user(session, current_user, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    result = list_messages(session, conversation, page=page, page_size=page_size, oldest_first=oldest_first)
    return MessageListResponse(
        items=[_serialize_message(msg, conversation) for msg in result.items],
        meta=PaginationMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev,
        ),
    )


@router.post("/{conversation_id}/read", response_model=MarkConversationReadResponse)
def mark_conversation_read_endpoint(
    conversation_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MarkConversationReadResponse:
    try:
        UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    conversation = get_conversation_for_user(session, current_user, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    conversation, already_read, unread_count = mark_conversation_read(session, conversation)
    return MarkConversationReadResponse(
        conversation_id=str(conversation.uuid),
        last_read_at=conversation.last_read_at,
        unread_count=unread_count,
        already_read=already_read,
    )
