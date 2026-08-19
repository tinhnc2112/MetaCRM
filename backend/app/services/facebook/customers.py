"""Customer profile and internal note services for Messenger CRM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from app.models.auth import User
from app.models.customer_core import Customer
from app.models.customers import CustomerMerge, CustomerNote, CustomerTag
from app.models.messenger import Conversation, Message
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.conversations import (
    PaginatedResult,
    get_conversation_for_user,
    get_user_page_ids,
    unread_count_for_conversation,
)
from app.services.facebook.customer_tags import list_tag_events_for_customer, list_tags_for_customer
from app.services.facebook.pages import get_current_page
from sqlalchemy import or_
from sqlalchemy.orm import Session


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _descending_nulls_last(column):
    """Return portable descending ordering with null values placed last."""
    return column.is_(None).asc(), column.desc()


@dataclass(frozen=True)
class CustomerTimelineItem:
    type: Literal["message", "note", "tag"]
    timestamp: datetime
    preview: str | None = None
    content: str | None = None
    is_from_page: bool | None = None
    action: Literal["added", "removed"] | None = None
    tag_name: str | None = None
    tag_slug: str | None = None


@dataclass(frozen=True)
class CustomerProfileData:
    customer: Customer
    conversation: Conversation
    conversations: list[Conversation]
    unread_count: int
    tags: list[CustomerTag]
    timeline: list[CustomerTimelineItem]
    notes: list[CustomerNote]


@dataclass(frozen=True)
class CustomerListItemData:
    customer: Customer
    avatar_url: str | None
    last_message_at: datetime | None
    conversation_count: int
    unread_count: int


def _message_preview(message: Message) -> str:
    return message.text or message.postback_payload or message.event_type


def _build_timeline(
    messages: list[Message],
    notes: list[CustomerNote],
    tag_events: list[CustomerTimelineItem],
) -> list[CustomerTimelineItem]:
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

    items.extend(tag_events)
    items.sort(key=lambda item: item.timestamp, reverse=True)
    return items


def _conversation_sort_key(conversation: Conversation) -> tuple[datetime, int]:
    timestamp = _utc(conversation.last_message_at or conversation.created_at)
    if timestamp is None:
        timestamp = datetime.min.replace(tzinfo=UTC)
    return timestamp, conversation.id


def _customer_conversations_for_page(session: Session, customer_id: int, facebook_page_id: int) -> list[Conversation]:
    return (
        session.query(Conversation)
        .filter(
            Conversation.customer_id == customer_id,
            Conversation.facebook_page_id == facebook_page_id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(
            *_descending_nulls_last(Conversation.last_message_at),
            Conversation.created_at.desc(),
            Conversation.id.desc(),
        )
        .all()
    )


def _customer_unread_count(session: Session, conversations: list[Conversation]) -> int:
    return sum(unread_count_for_conversation(session, conversation) for conversation in conversations)


def _build_customer_profile(
    session: Session,
    *,
    customer: Customer,
    conversation: Conversation,
    conversations: list[Conversation],
) -> CustomerProfileData:
    conversation_ids = [item.id for item in conversations] or [conversation.id]

    notes = (
        session.query(CustomerNote)
        .filter(
            CustomerNote.conversation_id.in_(conversation_ids),
            or_(
                CustomerNote.customer_id == customer.id,
                CustomerNote.customer_id.is_(None),
            ),
            CustomerNote.deleted_at.is_(None),
        )
        .order_by(
            CustomerNote.created_at.desc(),
            CustomerNote.updated_at.desc(),
            CustomerNote.id.desc(),
        )
        .all()
    )
    tags = list_tags_for_customer(session, customer.id, conversation.facebook_page_id)
    tag_events = [
        CustomerTimelineItem(
            type="tag",
            timestamp=event.timestamp,
            content=f"Tag {event.action}: {event.tag_name}",
            action=event.action,
            tag_name=event.tag_name,
            tag_slug=event.tag_slug,
        )
        for event in list_tag_events_for_customer(
            session, customer.id, conversation.facebook_page_id
        )
    ]
    messages = (
        session.query(Message)
        .filter(Message.conversation_id.in_(conversation_ids))
        .order_by(*_descending_nulls_last(Message.fb_timestamp_ms), Message.id.desc())
        .all()
    )
    sorted_conversations = sorted(conversations, key=_conversation_sort_key, reverse=True)
    return CustomerProfileData(
        customer=customer,
        conversation=conversation,
        conversations=sorted_conversations,
        unread_count=_customer_unread_count(session, sorted_conversations),
        tags=tags,
        timeline=_build_timeline(messages, notes, tag_events),
        notes=notes,
    )


def get_customer_profile(session: Session, user: User, conversation_id: str) -> CustomerProfileData | None:
    conversation = get_conversation_for_user(session, user, conversation_id)
    if conversation is None:
        return None
    current_page = get_current_page(session, user)
    if current_page is not None and conversation.facebook_page_id != current_page.id:
        return None

    # M19.5: Check if THIS SPECIFIC conversation was the secondary side of a
    # completed merge. This must be checked BEFORE resolving customer_id,
    # because merge_customers() re-points conversation.customer_id from the
    # secondary Customer to the primary Customer as part of the transfer
    # (any Conversation whose customer_id equals the secondary Customer's id
    # -- including the secondary conversation itself -- gets moved onto the
    # primary Customer). After that transfer, resolve_customer_for_conversation()
    # on the secondary conversation returns the PRIMARY customer_id, so a
    # check keyed on customer_id (e.g. Customer.merged_into_customer_id) would
    # incorrectly inspect the primary Customer's merge status instead of the
    # secondary's. Checking CustomerMerge.secondary_conversation_id directly
    # against this conversation's own id is unaffected by that remap.
    is_merged_away = (
        session.query(CustomerMerge)
        .filter(
            CustomerMerge.secondary_conversation_id == conversation.id,
            or_(
                CustomerMerge.primary_customer_id.is_(None),
                CustomerMerge.secondary_customer_id.is_(None),
                CustomerMerge.primary_customer_id != CustomerMerge.secondary_customer_id,
            ),
        )
        .first()
    ) is not None
    if is_merged_away:
        return None

    customer_id = resolve_customer_for_conversation(session, conversation)
    customer = session.get(Customer, customer_id)
    if customer is None or customer.deleted_at is not None:
        return None

    customer_conversations = _customer_conversations_for_page(session, customer.id, conversation.facebook_page_id)
    if not customer_conversations:
        customer_conversations = [conversation]

    return _build_customer_profile(
        session,
        customer=customer,
        conversation=conversation,
        conversations=customer_conversations,
    )


def get_customer_profile_by_uuid(session: Session, user: User, customer_uuid: str) -> CustomerProfileData | None:
    current_page = get_current_page(session, user)
    if current_page is None:
        return None

    try:
        customer_public_id = UUID(customer_uuid)
    except ValueError:
        return None

    customer = (
        session.query(Customer)
        .filter(
            Customer.public_id == customer_public_id,
            Customer.deleted_at.is_(None),
            Customer.merged_into_customer_id.is_(None),
        )
        .first()
    )
    if customer is None:
        return None

    conversations = _customer_conversations_for_page(session, customer.id, current_page.id)
    if not conversations:
        return None

    primary_conversation = conversations[0]
    return _build_customer_profile(
        session,
        customer=customer,
        conversation=primary_conversation,
        conversations=conversations,
    )


def list_customers(
    session: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
) -> PaginatedResult[CustomerListItemData] | None:
    current_page = get_current_page(session, user)
    if current_page is None:
        return None

    rows = (
        session.query(Conversation, Customer)
        .join(Customer, Customer.id == Conversation.customer_id)
        .filter(
            Conversation.facebook_page_id == current_page.id,
            Conversation.deleted_at.is_(None),
            Customer.deleted_at.is_(None),
            Customer.merged_into_customer_id.is_(None),
        )
        .order_by(
            *_descending_nulls_last(Conversation.last_message_at),
            Conversation.created_at.desc(),
            Conversation.id.desc(),
        )
        .all()
    )

    grouped: dict[int, dict[str, object]] = {}
    for conversation, customer in rows:
        group = grouped.get(customer.id)
        if group is None:
            group = {"customer": customer, "conversations": []}
            grouped[customer.id] = group
        conversations = group["conversations"]
        assert isinstance(conversations, list)
        conversations.append(conversation)

    search = query.strip().lower() if query and query.strip() else None
    if search is not None:
        filtered: dict[int, dict[str, object]] = {}
        for customer_id, group in grouped.items():
            customer = group["customer"]
            assert isinstance(customer, Customer)
            conversations = group["conversations"]
            assert isinstance(conversations, list)
            haystacks = [
                customer.name or "",
                customer.phone or "",
                customer.email or "",
                " ".join(conv.customer_name or "" for conv in conversations),
            ]
            if any(search in value.lower() for value in haystacks if value):
                filtered[customer_id] = group
        grouped = filtered

    customer_groups = list(grouped.values())
    customer_groups.sort(
        key=lambda group: (
            max(
                (
                    _conversation_sort_key(conversation)[0]
                    for conversation in group["conversations"]  # type: ignore[index]
                ),
                default=datetime.min.replace(tzinfo=UTC),
            ),
            group["customer"].id,  # type: ignore[index]
        ),
        reverse=True,
    )

    page = max(page, 1)
    page_size = min(page_size, 100)
    start = (page - 1) * page_size
    end = start + page_size
    visible_groups = customer_groups[start:end]

    items: list[CustomerListItemData] = []
    for group in visible_groups:
        customer = group["customer"]
        conversations = group["conversations"]
        assert isinstance(customer, Customer)
        assert isinstance(conversations, list)
        ordered_conversations = sorted(conversations, key=_conversation_sort_key, reverse=True)
        representative = ordered_conversations[0]
        last_message_at = max(
            (_conversation_sort_key(conversation)[0] for conversation in ordered_conversations),
            default=None,
        )
        unread_count = _customer_unread_count(session, ordered_conversations)
        items.append(
            CustomerListItemData(
                customer=customer,
                avatar_url=representative.customer_avatar_url,
                last_message_at=last_message_at,
                conversation_count=len(ordered_conversations),
                unread_count=unread_count,
            )
        )

    return PaginatedResult(
        items=items,
        total=len(customer_groups),
        page=page,
        page_size=page_size,
    )


def _get_note_for_user(session: Session, user: User, note_id: str) -> CustomerNote | None:
    current_page = get_current_page(session, user)
    allowed_page_ids = [current_page.id] if current_page is not None else get_user_page_ids(session, user)
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
            or_(
                CustomerNote.customer_id.is_(None),
                CustomerNote.customer_id == Conversation.customer_id,
            ),
        )
        .first()
    )


def create_customer_note(session: Session, user: User, conversation_id: str, content: str) -> CustomerNote | None:
    conversation = get_conversation_for_user(session, user, conversation_id)
    if conversation is None:
        return None
    current_page = get_current_page(session, user)
    if current_page is not None and conversation.facebook_page_id != current_page.id:
        return None

    customer_id = resolve_customer_for_conversation(session, conversation)
    note = CustomerNote(conversation_id=conversation.id, customer_id=customer_id, user_id=user.id, content=content)
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
