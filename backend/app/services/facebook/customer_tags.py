"""Customer tag services for Messenger CRM."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.models.auth import User
from app.models.customers import CustomerTag, CustomerTagAssignment, CustomerTagEvent
from app.models.facebook import FacebookPage
from app.models.messenger import Conversation
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.conversations import PaginatedResult, get_conversation_for_user
from app.services.facebook.pages import get_current_page
from app.services.facebook.query_ordering import descending_with_nulls_at_end
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CustomerTagData:
    id: int
    name: str
    slug: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    customer_count: int = 0


@dataclass(frozen=True)
class CustomerTagEventData:
    action: Literal["added", "removed"]
    timestamp: datetime
    tag_name: str
    tag_slug: str


@dataclass(frozen=True)
class CustomerTagAssignmentState:
    tag: CustomerTagData
    attached: bool


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or "tag"


def _current_page(session: Session, user: User) -> FacebookPage | None:
    return get_current_page(session, user)


def _tag_data(tag: CustomerTag, customer_count: int = 0) -> CustomerTagData:
    return CustomerTagData(
        id=tag.id,
        name=tag.name,
        slug=tag.slug,
        description=tag.description,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
        customer_count=customer_count,
    )


def _customer_count_map(session: Session, page: FacebookPage, tag_ids: list[int]) -> dict[int, int]:
    if not tag_ids:
        return {}
    # Count distinct customers (not assignment rows) so a Customer with
    # several conversations on this page (e.g. after a M19.5 merge) is only
    # counted once per tag.
    rows = (
        session.query(
            CustomerTagAssignment.tag_id,
            func.count(func.distinct(CustomerTagAssignment.customer_id)),
        )
        .join(Conversation, Conversation.id == CustomerTagAssignment.conversation_id)
        .filter(
            CustomerTagAssignment.tag_id.in_(tag_ids),
            Conversation.facebook_page_id == page.id,
            Conversation.deleted_at.is_(None),
            Conversation.customer_id == CustomerTagAssignment.customer_id,
        )
        .group_by(CustomerTagAssignment.tag_id)
        .all()
    )
    return {tag_id: int(count or 0) for tag_id, count in rows}


def _tag_for_page(session: Session, page_id: int, tag_id: int) -> CustomerTag | None:
    return (
        session.query(CustomerTag)
        .filter(CustomerTag.id == tag_id, CustomerTag.facebook_page_id == page_id)
        .first()
    )


def _count_existing_slug(session: Session, page_id: int, slug: str, exclude_tag_id: int | None = None) -> bool:
    query = session.query(CustomerTag.id).filter(
        CustomerTag.facebook_page_id == page_id,
        CustomerTag.slug == slug,
    )
    if exclude_tag_id is not None:
        query = query.filter(CustomerTag.id != exclude_tag_id)
    return session.query(query.exists()).scalar() is True


def _count_existing_name(session: Session, page_id: int, name: str, exclude_tag_id: int | None = None) -> bool:
    query = session.query(CustomerTag.id).filter(
        CustomerTag.facebook_page_id == page_id,
        CustomerTag.name == name,
    )
    if exclude_tag_id is not None:
        query = query.filter(CustomerTag.id != exclude_tag_id)
    return session.query(query.exists()).scalar() is True


def _generate_unique_slug(session: Session, page_id: int, name: str, exclude_tag_id: int | None = None) -> str:
    base = _slugify(name)
    slug = base
    suffix = 2
    while _count_existing_slug(session, page_id, slug, exclude_tag_id=exclude_tag_id):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def list_customer_tags(session: Session, user: User) -> list[CustomerTagData] | None:
    page = _current_page(session, user)
    if page is None:
        return None

    tags = (
        session.query(CustomerTag)
        .filter(CustomerTag.facebook_page_id == page.id)
        .order_by(CustomerTag.name.asc(), CustomerTag.id.asc())
        .all()
    )
    counts = _customer_count_map(session, page, [tag.id for tag in tags])
    return [_tag_data(tag, counts.get(tag.id, 0)) for tag in tags]


def get_customer_tag_for_page(session: Session, user: User, tag_id: int) -> CustomerTag | None:
    page = _current_page(session, user)
    if page is None:
        return None
    return _tag_for_page(session, page.id, tag_id)


def get_customer_tag_for_conversation(session: Session, conversation: Conversation, tag_id: int) -> CustomerTag | None:
    return _tag_for_page(session, conversation.facebook_page_id, tag_id)


def create_customer_tag(session: Session, user: User, name: str, description: str | None) -> CustomerTagData | None:
    page = _current_page(session, user)
    if page is None:
        return None

    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Tag name must not be empty")

    if _count_existing_name(session, page.id, cleaned_name):
        raise ValueError("Tag name already exists")

    tag = CustomerTag(
        facebook_page_id=page.id,
        name=cleaned_name,
        slug=_generate_unique_slug(session, page.id, cleaned_name),
        description=description.strip() if description and description.strip() else None,
    )
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return _tag_data(tag)


def update_customer_tag(
    session: Session,
    user: User,
    tag_id: int,
    name: str,
    description: str | None,
) -> CustomerTagData | None:
    tag = get_customer_tag_for_page(session, user, tag_id)
    if tag is None:
        return None

    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Tag name must not be empty")

    if cleaned_name != tag.name and _count_existing_name(session, tag.facebook_page_id, cleaned_name, exclude_tag_id=tag.id):
        raise ValueError("Tag name already exists")

    tag.name = cleaned_name
    tag.slug = _generate_unique_slug(session, tag.facebook_page_id, cleaned_name, exclude_tag_id=tag.id)
    tag.description = description.strip() if description and description.strip() else None
    session.add(tag)
    session.commit()
    session.refresh(tag)
    counts = _customer_count_map(session, _current_page(session, user) or tag.page, [tag.id])
    return _tag_data(tag, counts.get(tag.id, 0))


def delete_customer_tag(session: Session, user: User, tag_id: int) -> CustomerTagData | None:
    tag = get_customer_tag_for_page(session, user, tag_id)
    if tag is None:
        return None

    data = _tag_data(tag, _customer_count_map(session, tag.page, [tag.id]).get(tag.id, 0))
    session.delete(tag)
    session.commit()
    return data


def list_customer_tag_customers(
    session: Session,
    user: User,
    tag_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResult[Conversation] | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    tag = _tag_for_page(session, page_obj.id, tag_id)
    if tag is None:
        return None

    page_size = min(page_size, 100)
    page = max(page, 1)
    query = (
        session.query(Conversation)
        .join(CustomerTagAssignment, CustomerTagAssignment.conversation_id == Conversation.id)
        .filter(
            Conversation.facebook_page_id == page_obj.id,
            Conversation.deleted_at.is_(None),
            CustomerTagAssignment.tag_id == tag.id,
        )
    )
    total = query.count()
    items = (
        query.order_by(
            *descending_with_nulls_at_end(Conversation.last_message_at),
            Conversation.created_at.desc(),
            Conversation.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def list_tags_for_customer(session: Session, customer_id: int, facebook_page_id: int) -> list[CustomerTag]:
    """Tags owned by a Customer (M19.4), scoped to one page's tag vocabulary.

    Spans every conversation the Customer has on this page (not just the one
    currently open), since tag ownership belongs to the Customer.
    """
    return (
        session.query(CustomerTag)
        .join(CustomerTagAssignment, CustomerTagAssignment.tag_id == CustomerTag.id)
        .join(Conversation, Conversation.id == CustomerTagAssignment.conversation_id)
        .filter(
            CustomerTagAssignment.customer_id == customer_id,
            Conversation.customer_id == customer_id,
            Conversation.facebook_page_id == facebook_page_id,
            Conversation.deleted_at.is_(None),
            CustomerTag.facebook_page_id == facebook_page_id,
        )
        .order_by(CustomerTag.name.asc(), CustomerTag.id.asc())
        .distinct()
        .all()
    )


def list_tag_events_for_customer(
    session: Session, customer_id: int, facebook_page_id: int
) -> list[CustomerTagEventData]:
    rows = (
        session.query(CustomerTagEvent)
        .join(Conversation, Conversation.id == CustomerTagEvent.conversation_id)
        .outerjoin(CustomerTag, CustomerTag.id == CustomerTagEvent.tag_id)
        .filter(
            CustomerTagEvent.customer_id == customer_id,
            Conversation.customer_id == customer_id,
            Conversation.facebook_page_id == facebook_page_id,
            Conversation.deleted_at.is_(None),
            or_(
                CustomerTagEvent.tag_id.is_(None),
                and_(
                    CustomerTag.id.is_not(None),
                    CustomerTag.facebook_page_id == facebook_page_id,
                ),
            ),
        )
        .order_by(CustomerTagEvent.created_at.desc(), CustomerTagEvent.id.desc())
        .all()
    )
    events: list[CustomerTagEventData] = []
    for row in rows:
        timestamp = _utc(row.created_at)
        if timestamp is None:
            continue
        events.append(
            CustomerTagEventData(
                action=row.action,
                timestamp=timestamp,
                tag_name=row.tag_name_snapshot,
                tag_slug=row.tag_slug_snapshot,
            )
        )
    return events


def assign_customer_tag(
    session: Session,
    user: User,
    conversation_id: str,
    tag_id: int,
) -> CustomerTagAssignmentState | None:
    conversation = get_conversation_for_user(session, user, conversation_id)
    if conversation is None:
        return None
    current_page = _current_page(session, user)
    if current_page is not None and conversation.facebook_page_id != current_page.id:
        return None

    tag = get_customer_tag_for_conversation(session, conversation, tag_id)
    if tag is None:
        return None

    # M19.4: ownership/dedup is by customer_id, so assigning the same tag
    # from any of the Customer's conversations is idempotent.
    customer_id = resolve_customer_for_conversation(session, conversation)
    assignment = (
        session.query(CustomerTagAssignment)
        .filter(
            CustomerTagAssignment.customer_id == customer_id,
            CustomerTagAssignment.tag_id == tag.id,
        )
        .first()
    )
    if assignment is not None:
        assignment_conversation = session.get(Conversation, assignment.conversation_id)
        if (
            assignment_conversation is None
            or assignment_conversation.deleted_at is not None
            or assignment_conversation.facebook_page_id != conversation.facebook_page_id
            or assignment_conversation.customer_id != customer_id
        ):
            return None
    if assignment is None:
        assignment = CustomerTagAssignment(
            conversation_id=conversation.id, customer_id=customer_id, tag_id=tag.id
        )
        event = CustomerTagEvent(
            conversation_id=conversation.id,
            customer_id=customer_id,
            tag_id=tag.id,
            user_id=user.id,
            action="added",
            tag_name_snapshot=tag.name,
            tag_slug_snapshot=tag.slug,
        )
        session.add(assignment)
        session.add(event)
        session.commit()
    return CustomerTagAssignmentState(tag=_tag_data(tag), attached=True)


def remove_customer_tag(
    session: Session,
    user: User,
    conversation_id: str,
    tag_id: int,
) -> CustomerTagAssignmentState | None:
    conversation = get_conversation_for_user(session, user, conversation_id)
    if conversation is None:
        return None
    current_page = _current_page(session, user)
    if current_page is not None and conversation.facebook_page_id != current_page.id:
        return None

    tag = get_customer_tag_for_conversation(session, conversation, tag_id)
    if tag is None:
        return None

    customer_id = resolve_customer_for_conversation(session, conversation)
    assignment = (
        session.query(CustomerTagAssignment)
        .filter(
            CustomerTagAssignment.customer_id == customer_id,
            CustomerTagAssignment.tag_id == tag.id,
        )
        .first()
    )
    if assignment is not None:
        assignment_conversation = session.get(Conversation, assignment.conversation_id)
        if (
            assignment_conversation is None
            or assignment_conversation.deleted_at is not None
            or assignment_conversation.facebook_page_id != conversation.facebook_page_id
            or assignment_conversation.customer_id != customer_id
        ):
            return None
    if assignment is not None:
        event = CustomerTagEvent(
            conversation_id=conversation.id,
            customer_id=customer_id,
            tag_id=tag.id,
            user_id=user.id,
            action="removed",
            tag_name_snapshot=tag.name,
            tag_slug_snapshot=tag.slug,
        )
        session.delete(assignment)
        session.add(event)
        session.commit()

    return CustomerTagAssignmentState(tag=_tag_data(tag), attached=False)


def assign_customer_tag_to_conversation(
    session: Session,
    user: User,
    conversation_id: str,
    tag_id: int,
) -> CustomerTagAssignmentState | None:
    return assign_customer_tag(session, user, conversation_id, tag_id)


def remove_customer_tag_from_conversation(
    session: Session,
    user: User,
    conversation_id: str,
    tag_id: int,
) -> CustomerTagAssignmentState | None:
    return remove_customer_tag(session, user, conversation_id, tag_id)
