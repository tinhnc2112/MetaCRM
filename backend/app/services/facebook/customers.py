"""Customer profile and internal note services for Messenger CRM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from app.models.auth import User
from app.models.customers import CustomerNote
from app.models.messenger import Conversation, Message
from app.services.facebook.conversations import (
    get_conversation_for_user,
    get_user_page_ids,
    unread_count_for_conversation,
)
from sqlalchemy.orm import Session


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class CustomerTimelineItem:
    type: Literal["message", "note"]
    timestamp: datetime
    preview: str | None = None
    content: str | None = None
    is_from_page: bool | None = None


@dataclass(frozen=True)
class CustomerProfileData:
    conversation: Conversation
    unread_count: int
    timeline: list[CustomerTimelineItem]
    notes: list[CustomerNote]


def _message_preview(message: Message) -> str:
    return message.text or message.postback_payload or message.event_type


def _build_timeline(messages: list[Message], notes: list[CustomerNote]) -> list[CustomerTimelineItem]:
    items: list[CustomerTimelineItem] = []
    for message in messages:
        timestamp = _utc(message.sent_at or message.created_at)
        if timestamp is None:
            continue
        items.append(
            CustomerTimelineItem(
                type="message",
                timestamp=timestamp,
                preview=_message_preview(message),
                is_from_page=message.is_from_page,
            )
        )

    for note in notes:
        timestamp = _utc(note.created_at or note.updated_at)
        if timestamp is None:
            continue
        items.append(
            CustomerTimelineItem(
                type="note",
                timestamp=timestamp,
                content=note.content,
            )
        )

    items.sort(key=lambda item: item.timestamp, reverse=True)
    return items


def get_customer_profile(session: Session, user: User, conversation_id: str) -> CustomerProfileData | None:
    conversation = get_conversation_for_user(session, user, conversation_id)
    if conversation is None:
        return None

    notes = (
        session.query(CustomerNote)
        .filter(
            CustomerNote.conversation_id == conversation.id,
            CustomerNote.deleted_at.is_(None),
        )
        .order_by(
            CustomerNote.created_at.desc(),
            CustomerNote.updated_at.desc(),
            CustomerNote.id.desc(),
        )
        .all()
    )
    messages = (
        session.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.fb_timestamp_ms.desc().nulls_last(), Message.id.desc())
        .all()
    )
    return CustomerProfileData(
        conversation=conversation,
        unread_count=unread_count_for_conversation(session, conversation),
        timeline=_build_timeline(messages, notes),
        notes=notes,
    )


def _get_note_for_user(session: Session, user: User, note_id: str) -> CustomerNote | None:
    allowed_page_ids = get_user_page_ids(session, user)
    if not allowed_page_ids:
        return None
    try:
        note_uuid = UUID(note_id)
    except ValueError:
        return None
    return (
        session.query(CustomerNote)
        .join(Conversation, Conversation.id == CustomerNote.conversation_id)
        .filter(
            CustomerNote.uuid == note_uuid,
            CustomerNote.deleted_at.is_(None),
            Conversation.facebook_page_id.in_(allowed_page_ids),
            Conversation.deleted_at.is_(None),
        )
        .first()
    )


def create_customer_note(session: Session, user: User, conversation_id: str, content: str) -> CustomerNote | None:
    conversation = get_conversation_for_user(session, user, conversation_id)
    if conversation is None:
        return None

    note = CustomerNote(conversation_id=conversation.id, user_id=user.id, content=content)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def update_customer_note(session: Session, user: User, note_id: str, content: str) -> CustomerNote | None:
    note = _get_note_for_user(session, user, note_id)
    if note is None:
        return None

    note.content = content
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def delete_customer_note(session: Session, user: User, note_id: str) -> CustomerNote | None:
    note = _get_note_for_user(session, user, note_id)
    if note is None:
        return None

    note.deleted_at = datetime.now(UTC)
    session.add(note)
    session.commit()
    return note
