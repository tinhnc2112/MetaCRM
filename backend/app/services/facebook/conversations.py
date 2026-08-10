"""CRM read services for Messenger conversations and messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID

from app.models.auth import User
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation, Message
from sqlalchemy.orm import Session

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Shared dataclass for paginated results
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Authorization helper
# ---------------------------------------------------------------------------


def get_user_page_ids(session: Session, user: User) -> list[int]:
    """Return the list of FacebookPage PKs the user has access to.

    A user owns a page when their ``FacebookAccount`` (via user_id) has that
    page linked via ``facebook_account_id``.  Deleted accounts / pages are
    excluded.
    """
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


# ---------------------------------------------------------------------------
# Conversation queries
# ---------------------------------------------------------------------------


def list_conversations(
    session: Session,
    user: User,
    *,
    page_id_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResult[Conversation]:
    """Return a paginated, newest-first list of conversations the user can see.

    Access control: only conversations whose ``facebook_page_id`` belongs to a
    page the user owns are returned.

    Args:
        session: DB session.
        user: Authenticated user.
        page_id_filter: Optional Facebook page_id string to narrow results.
        page: 1-based page number.
        page_size: Number of items per page (max 100).
    """
    page_size = min(page_size, 100)
    page = max(page, 1)

    allowed_page_ids = get_user_page_ids(session, user)
    if not allowed_page_ids:
        return PaginatedResult(items=[], total=0, page=page, page_size=page_size)

    query = (
        session.query(Conversation)
        .filter(
            Conversation.facebook_page_id.in_(allowed_page_ids),
            Conversation.deleted_at.is_(None),
        )
    )

    if page_id_filter is not None:
        query = query.filter(Conversation.page_id == page_id_filter)

    total = query.count()

    items = (
        query
        .order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def get_conversation_for_user(
    session: Session,
    user: User,
    conversation_uuid: str,
) -> Conversation | None:
    """Return the conversation if the user has access, else None.

    Uses UUID (not integer PK) as the public identifier to avoid enumeration.
    """
    allowed_page_ids = get_user_page_ids(session, user)
    if not allowed_page_ids:
        return None

    # Convert string UUID to UUID object for proper comparison in SQLAlchemy
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


# ---------------------------------------------------------------------------
# Message queries
# ---------------------------------------------------------------------------


def list_messages(
    session: Session,
    conversation: Conversation,
    *,
    page: int = 1,
    page_size: int = 50,
    oldest_first: bool = False,
) -> PaginatedResult[Message]:
    """Return paginated messages for a conversation.

    Default ordering is newest-first (most recent messages at the top of the
    response), which is typical for chat UIs that load earlier history.
    Set ``oldest_first=True`` to get chronological order.

    Args:
        session: DB session.
        conversation: Already-authorised Conversation instance.
        page: 1-based page number.
        page_size: Items per page (max 100).
        oldest_first: If True, order ascending by sent_at / fb_timestamp_ms.
    """
    page_size = min(page_size, 100)
    page = max(page, 1)

    query = session.query(Message).filter(
        Message.conversation_id == conversation.id
    )

    total = query.count()

    if oldest_first:
        order_primary = Message.fb_timestamp_ms.asc().nulls_last()
        order_secondary = Message.id.asc()
    else:
        order_primary = Message.fb_timestamp_ms.desc().nulls_last()
        order_secondary = Message.id.desc()

    items = (
        query
        .order_by(order_primary, order_secondary)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)
