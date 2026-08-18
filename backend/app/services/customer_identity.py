"""Customer Core: resolve channel identities to a stable Customer.

This is the single place that maps a (channel, external_id) pair to a
Customer row. Every channel adapter (Facebook Messenger today; other
channels later) must go through this service instead of creating or
looking up Customer/CustomerIdentity rows directly, so the mapping logic
and identity uniqueness stay centralized (see docs/03_CUSTOMER.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.base import utc_now
from app.models.customer_core import Customer, CustomerIdentity
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CHANNEL_FACEBOOK = "FACEBOOK"


class CustomerIdentityConsistencyError(ValueError):
    """Raised when a scoped identity and Conversation disagree on Customer ownership."""


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalise to UTC-aware. SQLite (tests) drops tzinfo on read-back even
    for ``DateTime(timezone=True)`` columns, so naive values are treated as
    already-UTC to avoid ``TypeError`` when compared against aware values.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def resolve_root_customer(session: Session, customer_id: int) -> Customer | None:
    """Resolve a canonical Customer root and reject corrupted merge cycles."""
    current = session.get(Customer, customer_id)
    seen: set[int] = set()
    while current is not None:
        if current.id in seen:
            raise CustomerIdentityConsistencyError("Customer merge cycle detected")
        seen.add(current.id)
        if current.merged_into_customer_id is None:
            return current
        current = session.get(Customer, current.merged_into_customer_id)
    return None


def _find_customer_identity(
    session: Session,
    *,
    channel: str,
    facebook_page_id: int,
    external_id: str,
) -> CustomerIdentity | None:
    return (
        session.query(CustomerIdentity)
        .filter(
            CustomerIdentity.channel == channel,
            CustomerIdentity.facebook_page_id == facebook_page_id,
            CustomerIdentity.external_id == external_id,
        )
        .first()
    )


def _update_identity_profile(
    session: Session,
    identity: CustomerIdentity,
    *,
    display_name: str | None,
    avatar_url: str | None,
    seen_at: datetime,
) -> None:
    updated = False
    if display_name and not identity.display_name:
        identity.display_name = display_name
        updated = True
    if avatar_url and not identity.avatar_url:
        identity.avatar_url = avatar_url
        updated = True
    seen_at_utc = _ensure_utc(seen_at)
    last_seen_utc = _ensure_utc(identity.last_seen_at)
    if last_seen_utc is None or (seen_at_utc is not None and seen_at_utc > last_seen_utc):
        identity.last_seen_at = seen_at
        updated = True
    if updated:
        session.add(identity)
        session.flush()


def _create_scoped_identity(
    session: Session,
    *,
    channel: str,
    facebook_page_id: int,
    external_id: str,
    display_name: str | None,
    avatar_url: str | None,
    seen_at: datetime,
    customer: Customer | None = None,
) -> CustomerIdentity:
    """Create Customer+identity in a savepoint and reload a concurrent winner."""
    try:
        with session.begin_nested():
            scoped_customer = customer
            if scoped_customer is None:
                scoped_customer = Customer(name=display_name, status="ACTIVE")
                session.add(scoped_customer)
                session.flush()
            identity = CustomerIdentity(
                customer_id=scoped_customer.id,
                facebook_page_id=facebook_page_id,
                channel=channel,
                external_id=external_id,
                display_name=display_name,
                avatar_url=avatar_url,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )
            session.add(identity)
            session.flush()
    except IntegrityError:
        winner = _find_customer_identity(
            session,
            channel=channel,
            facebook_page_id=facebook_page_id,
            external_id=external_id,
        )
        if winner is None:
            raise
        return winner
    return identity


def get_or_create_customer_identity(
    session: Session,
    *,
    channel: str,
    external_id: str,
    facebook_page_id: int,
    display_name: str | None = None,
    avatar_url: str | None = None,
    seen_at: datetime | None = None,
) -> CustomerIdentity:
    """Return the Page-scoped identity, or create a Customer+identity pair.

    Idempotent for the same ``(channel, facebook_page_id, external_id)``.
    Does not commit; caller controls the transaction boundary.
    """
    seen_at = seen_at or utc_now()

    identity = _find_customer_identity(
        session,
        channel=channel,
        facebook_page_id=facebook_page_id,
        external_id=external_id,
    )

    if identity is not None:
        _update_identity_profile(
            session,
            identity,
            display_name=display_name,
            avatar_url=avatar_url,
            seen_at=seen_at,
        )
        return identity

    identity = _create_scoped_identity(
        session,
        channel=channel,
        facebook_page_id=facebook_page_id,
        external_id=external_id,
        display_name=display_name,
        avatar_url=avatar_url,
        seen_at=seen_at,
    )
    _update_identity_profile(
        session,
        identity,
        display_name=display_name,
        avatar_url=avatar_url,
        seen_at=seen_at,
    )
    return identity


def resolve_customer_for_conversation(session: Session, conversation) -> int:
    """Return ``conversation.customer_id``, resolving/creating it if unset.

    This is the single choke point for M19.6 ("automatic Customer resolution
    for newly-created Conversations"): any code path that touches a
    Conversation without a linked Customer will lazily create the
    CustomerIdentity mapping here instead of failing or leaving customer_id
    NULL. Existing links are checked against the Page-scoped identity and
    canonical merge root before being returned.
    """
    facebook_page_id = conversation.facebook_page_id
    if facebook_page_id is None:
        raise CustomerIdentityConsistencyError("Conversation has no Facebook Page scope")

    identity = _find_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=facebook_page_id,
        external_id=conversation.psid,
    )

    if conversation.customer_id is not None:
        conversation_root = resolve_root_customer(session, conversation.customer_id)
        if conversation_root is None:
            raise CustomerIdentityConsistencyError("Conversation references a missing Customer")

        if identity is None:
            identity = _create_scoped_identity(
                session,
                channel=CHANNEL_FACEBOOK,
                facebook_page_id=facebook_page_id,
                external_id=conversation.psid,
                display_name=conversation.customer_name,
                avatar_url=conversation.customer_avatar_url,
                seen_at=utc_now(),
                customer=conversation_root,
            )

        identity_root = resolve_root_customer(session, identity.customer_id)
        if identity_root is None or identity_root.id != conversation_root.id:
            raise CustomerIdentityConsistencyError(
                "Scoped CustomerIdentity belongs to a different Customer"
            )

        changed = False
        if conversation.customer_id != conversation_root.id:
            conversation.customer_id = conversation_root.id
            session.add(conversation)
            changed = True
        if identity.customer_id != conversation_root.id:
            identity.customer_id = conversation_root.id
            session.add(identity)
            changed = True
        if changed:
            session.flush()
        _update_identity_profile(
            session,
            identity,
            display_name=conversation.customer_name,
            avatar_url=conversation.customer_avatar_url,
            seen_at=utc_now(),
        )
        return conversation_root.id

    identity = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=facebook_page_id,
        external_id=conversation.psid,
        display_name=conversation.customer_name,
        avatar_url=conversation.customer_avatar_url,
    )
    identity_root = resolve_root_customer(session, identity.customer_id)
    if identity_root is None:
        raise CustomerIdentityConsistencyError(
            "Scoped CustomerIdentity references a missing Customer"
        )
    if identity.customer_id != identity_root.id:
        identity.customer_id = identity_root.id
        session.add(identity)
    conversation.customer_id = identity_root.id
    session.add(conversation)
    session.flush()
    return conversation.customer_id


@dataclass
class BackfillResult:
    conversations_scanned: int
    conversations_linked: int
    customers_created: int


def backfill_conversation_customers(session: Session) -> BackfillResult:
    """Link every existing facebook_conversations row without customer_id to
    a Customer, creating one identity per distinct Facebook Page + PSID.

    Repeatable/idempotent: conversations that already have customer_id are
    skipped; scoped identities are checked before a new Customer is created.
    """
    # Local import to avoid a module-level circular import between
    # app.models.messenger and app.services.customer_identity.
    from app.models.messenger import Conversation

    conversations = (
        session.query(Conversation)
        .filter(Conversation.customer_id.is_(None), Conversation.deleted_at.is_(None))
        .all()
    )

    linked = 0
    customers_before = session.query(Customer).count()

    for conversation in conversations:
        identity = get_or_create_customer_identity(
            session,
            channel=CHANNEL_FACEBOOK,
            facebook_page_id=conversation.facebook_page_id,
            external_id=conversation.psid,
            display_name=conversation.customer_name,
            avatar_url=conversation.customer_avatar_url,
        )
        conversation.customer_id = identity.customer_id
        session.add(conversation)
        linked += 1

    session.flush()
    customers_after = session.query(Customer).count()

    return BackfillResult(
        conversations_scanned=len(conversations),
        conversations_linked=linked,
        customers_created=customers_after - customers_before,
    )
