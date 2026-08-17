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
from sqlalchemy.orm import Session

CHANNEL_FACEBOOK = "FACEBOOK"


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


def _resolve_root_customer(session: Session, customer_id: int) -> Customer | None:
    current = session.get(Customer, customer_id)
    seen: set[int] = set()
    while current is not None and current.merged_into_customer_id is not None and current.id not in seen:
        seen.add(current.id)
        current = session.get(Customer, current.merged_into_customer_id)
    return current


def get_or_create_customer_identity(
    session: Session,
    *,
    channel: str,
    external_id: str,
    display_name: str | None = None,
    avatar_url: str | None = None,
    seen_at: datetime | None = None,
) -> CustomerIdentity:
    """Return the existing CustomerIdentity for (channel, external_id), or
    create a new Customer + CustomerIdentity pair if none exists yet.

    Idempotent: safe to call repeatedly for the same (channel, external_id).
    Does not commit; caller controls the transaction boundary.
    """
    seen_at = seen_at or utc_now()

    identity = (
        session.query(CustomerIdentity)
        .filter(
            CustomerIdentity.channel == channel,
            CustomerIdentity.external_id == external_id,
        )
        .first()
    )

    if identity is not None:
        updated = False
        if display_name and not identity.display_name:
            identity.display_name = display_name
            updated = True
        if avatar_url and not identity.avatar_url:
            identity.avatar_url = avatar_url
            updated = True
        seen_at_utc = _ensure_utc(seen_at)
        last_seen_utc = _ensure_utc(identity.last_seen_at)
        if last_seen_utc is None or seen_at_utc > last_seen_utc:
            identity.last_seen_at = seen_at
            updated = True
        if updated:
            session.add(identity)
            session.flush()
        return identity

    customer = Customer(
        name=display_name,
        status="ACTIVE",
    )
    session.add(customer)
    session.flush()  # obtain customer.id

    identity = CustomerIdentity(
        customer_id=customer.id,
        channel=channel,
        external_id=external_id,
        display_name=display_name,
        avatar_url=avatar_url,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    session.add(identity)
    session.flush()
    return identity


def resolve_customer_for_conversation(session: Session, conversation) -> int:
    """Return ``conversation.customer_id``, resolving/creating it if unset.

    This is the single choke point for M19.6 ("automatic Customer resolution
    for newly-created Conversations"): any code path that touches a
    Conversation without a linked Customer will lazily create the
    CustomerIdentity mapping here instead of failing or leaving customer_id
    NULL. Idempotent: a Conversation that already has customer_id is
    returned unchanged (no extra queries).
    """
    if conversation.customer_id is not None:
        root_customer = _resolve_root_customer(session, conversation.customer_id)
        if root_customer is not None and root_customer.id != conversation.customer_id:
            conversation.customer_id = root_customer.id
            session.add(conversation)
            session.flush()
        customer_id = conversation.customer_id
        identity = (
            session.query(CustomerIdentity)
            .filter(
                CustomerIdentity.channel == CHANNEL_FACEBOOK,
                CustomerIdentity.external_id == conversation.psid,
            )
            .first()
        )
        if identity is not None:
            updated = False
            if identity.customer_id != customer_id:
                identity.customer_id = customer_id
                updated = True
            if conversation.customer_name and not identity.display_name:
                identity.display_name = conversation.customer_name
                updated = True
            if conversation.customer_avatar_url and not identity.avatar_url:
                identity.avatar_url = conversation.customer_avatar_url
                updated = True
            if updated:
                session.add(identity)
                session.flush()
            return customer_id

        identity = CustomerIdentity(
            customer_id=customer_id,
            channel=CHANNEL_FACEBOOK,
            external_id=conversation.psid,
            display_name=conversation.customer_name,
            avatar_url=conversation.customer_avatar_url,
        )
        session.add(identity)
        session.flush()
        return customer_id

    identity = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        external_id=conversation.psid,
        display_name=conversation.customer_name,
        avatar_url=conversation.customer_avatar_url,
    )
    conversation.customer_id = identity.customer_id
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
    a Customer, creating one CustomerIdentity(channel=FACEBOOK, external_id=psid)
    per distinct PSID.

    Repeatable/idempotent: conversations that already have customer_id are
    skipped; identities are looked up by the (channel, external_id) unique
    constraint before a new Customer is created.
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
