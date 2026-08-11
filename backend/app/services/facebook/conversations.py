"""CRM read services for Messenger conversations and messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar
from uuid import UUID

from app.models.auth import User
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from sqlalchemy import func
from sqlalchemy.orm import Session

T = TypeVar("T")


@dataclass
class PaginatedResult(Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total

    @property
    def has_prev(self) -> bool:
        return self.page > 1


def get_user_page_ids(session: Session, user: User) -> list[int]:
    rows = (
        session.query(FacebookPage.id)
        .join(FacebookAccount, FacebookAccount.id == FacebookPage.facebook_account_id)
        .filter(
            FacebookAccount.user_id == user.id,
            FacebookAccount.is_active.is_(True),
            FacebookAccount.deleted_at.is_(None),
            FacebookPage.deleted_at.is_(None),
        )
        .all()
    )
    return [row[0] for row in rows]


def _latest_message(session: Session, conversation_id: int) -> Message | None:
    return (
        session.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.fb_timestamp_ms.desc().nulls_last(), Message.id.desc())
        .first()
    )


def unread_count_for_conversation(session: Session, conversation: Conversation) -> int:
    query = session.query(func.count(Message.id)).filter(
        Message.conversation_id == conversation.id,
        Message.is_from_page.is_(False),
    )
    if conversation.last_read_at is not None:
        query = query.filter(Message.sent_at.is_not(None), Message.sent_at > conversation.last_read_at)
    return int(query.scalar() or 0)


def conversation_last_message_preview(session: Session, conversation: Conversation) -> str | None:
    message = _latest_message(session, conversation.id)
    if message is None:
        return None
    if message.text:
        return message.text
    if message.postback_payload:
        return message.postback_payload
    return message.event_type


def list_conversations(
    session: Session,
    user: User,
    *,
    page_id_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResult[Conversation]:
    page_size = min(page_size, 100)
    page = max(page, 1)

    allowed_page_ids = get_user_page_ids(session, user)
    if not allowed_page_ids:
        return PaginatedResult(items=[], total=0, page=page, page_size=page_size)

    query = session.query(Conversation).filter(
        Conversation.facebook_page_id.in_(allowed_page_ids),
        Conversation.deleted_at.is_(None),
    )
    if page_id_filter is not None:
        query = query.filter(Conversation.page_id == page_id_filter)

    total = query.count()
    items = (
        query.order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def get_conversation_for_user(session: Session, user: User, conversation_uuid: str) -> Conversation | None:
    allowed_page_ids = get_user_page_ids(session, user)
    if not allowed_page_ids:
        return None
    try:
        uuid_obj = UUID(conversation_uuid)
    except ValueError:
        return None
    return (
        session.query(Conversation)
        .filter(
            Conversation.uuid == uuid_obj,
            Conversation.facebook_page_id.in_(allowed_page_ids),
            Conversation.deleted_at.is_(None),
        )
        .first()
    )


def list_messages(
    session: Session,
    conversation: Conversation,
    *,
    page: int = 1,
    page_size: int = 50,
    oldest_first: bool = False,
) -> PaginatedResult[Message]:
    page_size = min(page_size, 100)
    page = max(page, 1)

    query = session.query(Message).filter(Message.conversation_id == conversation.id)
    total = query.count()

    if oldest_first:
        order_primary = Message.fb_timestamp_ms.asc().nulls_last()
        order_secondary = Message.id.asc()
    else:
        order_primary = Message.fb_timestamp_ms.desc().nulls_last()
        order_secondary = Message.id.desc()

    items = (
        query.order_by(order_primary, order_secondary)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def mark_conversation_read(session: Session, conversation: Conversation) -> tuple[Conversation, bool, int]:
    latest = conversation.last_message_at or datetime.now(UTC)
    already_read = conversation.last_read_at is not None and conversation.last_read_at >= latest
    if not already_read:
        conversation.last_read_at = latest
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
    unread_count = unread_count_for_conversation(session, conversation)
    return conversation, already_read, unread_count
