"""Customer duplicate detection and merge services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.models.auth import User
from app.models.customer_core import Customer, CustomerIdentity
from app.models.customers import CustomerMerge, CustomerNote, CustomerTagAssignment, CustomerTagEvent
from app.models.messenger import Conversation
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.conversations import PaginatedResult
from app.services.facebook.pages import get_current_page
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CustomerDuplicateData:
    primary_customer: Conversation
    duplicate_customer: Conversation
    confidence: float
    reason: str
    matching_fields: list[str]
    matching_signals: list[str]


@dataclass(frozen=True)
class CustomerMergeData:
    merge: CustomerMerge
    primary_customer: Conversation
    secondary_customer: Conversation


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _current_page(session: Session, user: User):
    return get_current_page(session, user)


def _conversation_for_page(
    session: Session,
    page_id: int,
    conversation_uuid: str,
    *,
    include_deleted: bool = False,
) -> Conversation | None:
    try:
        uuid_obj = UUID(conversation_uuid)
    except ValueError:
        return None
    query = session.query(Conversation).filter(
        Conversation.uuid == uuid_obj,
        Conversation.facebook_page_id == page_id,
    )
    if not include_deleted:
        query = query.filter(Conversation.deleted_at.is_(None))
    return (
        query.first()
    )


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _normalize_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _duplicate_signals(primary: Conversation, duplicate: Conversation) -> tuple[float, str, list[str], list[str]] | None:
    matching_fields: list[str] = []
    matching_signals: list[str] = []
    confidence = 0.0
    reason = ""

    if primary.psid == duplicate.psid:
        matching_fields.append("psid")
        matching_signals.append(f"Shared PSID {primary.psid}")
        confidence = 1.0
        reason = "Matched the same PSID"

    primary_name = _normalize_text(primary.customer_name)
    duplicate_name = _normalize_text(duplicate.customer_name)
    primary_avatar = _normalize_url(primary.customer_avatar_url)
    duplicate_avatar = _normalize_url(duplicate.customer_avatar_url)

    if primary_name and duplicate_name and primary_name == duplicate_name and primary_avatar and duplicate_avatar and primary_avatar == duplicate_avatar:
        matching_fields.extend(["customer_name", "customer_avatar_url"])
        matching_signals.append("Matched customer name and avatar URL")
        if confidence < 0.9:
            confidence = 0.9
            reason = "Matched the same customer name and avatar URL"

    if primary_avatar and duplicate_avatar and primary_avatar == duplicate_avatar:
        matching_fields.append("customer_avatar_url")
        matching_signals.append(f"Shared avatar URL {primary_avatar}")
        if confidence < 0.75:
            confidence = 0.75
            reason = "Matched the same avatar URL"

    if not matching_fields:
        return None

    deduped_fields = list(dict.fromkeys(matching_fields))
    deduped_signals = list(dict.fromkeys(matching_signals))
    if not reason:
        reason = "Matched explicit customer identity signals"
    return confidence, reason, deduped_fields, deduped_signals


def _pair_key(first: int, second: int) -> tuple[int, int]:
    return (first, second) if first < second else (second, first)


def _duplicate_primary_duplicate_pair(first: Conversation, second: Conversation) -> tuple[Conversation, Conversation]:
    first_key = (_utc(first.created_at) or first.created_at, first.id)
    second_key = (_utc(second.created_at) or second.created_at, second.id)
    if first_key <= second_key:
        return first, second
    return second, first


def list_customer_duplicates(
    session: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResult[CustomerDuplicateData] | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    page_size = min(page_size, 100)
    page = max(page, 1)

    conversations = (
        session.query(Conversation)
        .filter(
            Conversation.facebook_page_id == page_obj.id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.created_at.desc(),
            Conversation.id.desc(),
        )
        .all()
    )
    if len(conversations) < 2:
        return PaginatedResult(items=[], total=0, page=page, page_size=page_size)

    pair_map: dict[tuple[int, int], CustomerDuplicateData] = {}
    grouped: dict[str, list[Conversation]] = {}
    grouped_avatar: dict[str, list[Conversation]] = {}
    grouped_name_avatar: dict[tuple[str, str], list[Conversation]] = {}

    for conversation in conversations:
        if conversation.psid:
            grouped.setdefault(f"psid:{conversation.psid}", []).append(conversation)
        avatar = _normalize_url(conversation.customer_avatar_url)
        if avatar:
            grouped_avatar.setdefault(avatar, []).append(conversation)
        name = _normalize_text(conversation.customer_name)
        if name and avatar:
            grouped_name_avatar.setdefault((name, avatar), []).append(conversation)

    for bucket in grouped.values():
        if len(bucket) < 2:
            continue
        for index, first in enumerate(bucket):
            for second in bucket[index + 1 :]:
                confidence_reason = _duplicate_signals(first, second)
                if confidence_reason is None:
                    continue
                confidence, reason, matching_fields, matching_signals = confidence_reason
                primary, duplicate = _duplicate_primary_duplicate_pair(first, second)
                pair_map[_pair_key(primary.id, duplicate.id)] = CustomerDuplicateData(
                    primary_customer=primary,
                    duplicate_customer=duplicate,
                    confidence=confidence,
                    reason=reason,
                    matching_fields=matching_fields,
                    matching_signals=matching_signals,
                )

    for bucket in grouped_avatar.values():
        if len(bucket) < 2:
            continue
        for index, first in enumerate(bucket):
            for second in bucket[index + 1 :]:
                confidence_reason = _duplicate_signals(first, second)
                if confidence_reason is None:
                    continue
                confidence, reason, matching_fields, matching_signals = confidence_reason
                primary, duplicate = _duplicate_primary_duplicate_pair(first, second)
                key = _pair_key(primary.id, duplicate.id)
                existing = pair_map.get(key)
                if existing is None or confidence > existing.confidence:
                    pair_map[key] = CustomerDuplicateData(
                        primary_customer=primary,
                        duplicate_customer=duplicate,
                        confidence=confidence,
                        reason=reason,
                        matching_fields=matching_fields,
                        matching_signals=matching_signals,
                    )

    for bucket in grouped_name_avatar.values():
        if len(bucket) < 2:
            continue
        for index, first in enumerate(bucket):
            for second in bucket[index + 1 :]:
                confidence_reason = _duplicate_signals(first, second)
                if confidence_reason is None:
                    continue
                confidence, reason, matching_fields, matching_signals = confidence_reason
                primary, duplicate = _duplicate_primary_duplicate_pair(first, second)
                key = _pair_key(primary.id, duplicate.id)
                existing = pair_map.get(key)
                if existing is None or confidence > existing.confidence:
                    pair_map[key] = CustomerDuplicateData(
                        primary_customer=primary,
                        duplicate_customer=duplicate,
                        confidence=confidence,
                        reason=reason,
                        matching_fields=matching_fields,
                        matching_signals=matching_signals,
                    )

    items = sorted(
        pair_map.values(),
        key=lambda item: (
            -item.confidence,
            _utc(item.primary_customer.created_at) or item.primary_customer.created_at,
            _utc(item.duplicate_customer.created_at) or item.duplicate_customer.created_at,
            item.primary_customer.id,
            item.duplicate_customer.id,
        ),
    )
    total = len(items)
    items = items[(page - 1) * page_size : (page - 1) * page_size + page_size]
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def _get_merge_by_customer_pair(
    session: Session, primary_customer_id: int, secondary_customer_id: int
) -> CustomerMerge | None:
    return (
        session.query(CustomerMerge)
        .filter(
            CustomerMerge.primary_customer_id == primary_customer_id,
            CustomerMerge.secondary_customer_id == secondary_customer_id,
        )
        .order_by(CustomerMerge.created_at.desc(), CustomerMerge.id.desc())
        .first()
    )


def _get_merge_by_secondary_customer(session: Session, secondary_customer_id: int) -> CustomerMerge | None:
    return (
        session.query(CustomerMerge)
        .filter(CustomerMerge.secondary_customer_id == secondary_customer_id)
        .order_by(CustomerMerge.created_at.desc(), CustomerMerge.id.desc())
        .first()
    )


def _get_merge_by_conversation_pair(
    session: Session, primary_conversation_id: int, secondary_conversation_id: int
) -> CustomerMerge | None:
    """Check if this conversation pair has already been merged (UNIQUE constraint check)."""
    return (
        session.query(CustomerMerge)
        .filter(
            CustomerMerge.primary_conversation_id == primary_conversation_id,
            CustomerMerge.secondary_conversation_id == secondary_conversation_id,
        )
        .first()
    )


def merge_customers(
    session: Session,
    user: User,
    primary_customer_id: str,
    secondary_customer_id: str,
) -> CustomerMergeData | None:
    """Merge the Customer behind `secondary_customer_id` into the Customer
    behind `primary_customer_id` (M19.5: "Merge Customer, never only
    Conversation", docs/03_CUSTOMER.md).

    The API/UI still identify the two sides by Conversation UUID (unchanged
    contract), but the actual merge atomically transfers every
    CustomerIdentity, Conversation, CustomerNote and CustomerTagAssignment
    that belongs to the secondary Customer onto the primary Customer. Both
    conversations remain independently accessible afterwards; only their
    shared Customer-owned data (tags/notes) becomes unified.
    """
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    primary = _conversation_for_page(session, page_obj.id, primary_customer_id)
    secondary = _conversation_for_page(session, page_obj.id, secondary_customer_id, include_deleted=True)
    if primary is None or secondary is None:
        return None

    if primary.id == secondary.id:
        raise ValueError("Cannot merge a customer into itself")

    # Idempotency check: if this conversation pair was already merged, return the existing record
    # This check happens BEFORE any data transfer to prevent UNIQUE constraint violations on retry
    existing_merge_by_pair = _get_merge_by_conversation_pair(session, primary.id, secondary.id)
    if existing_merge_by_pair is not None:
        return CustomerMergeData(merge=existing_merge_by_pair, primary_customer=primary, secondary_customer=secondary)

    primary_customer_pk = resolve_customer_for_conversation(session, primary)
    secondary_customer_pk = resolve_customer_for_conversation(session, secondary)

    primary_customer = session.get(Customer, primary_customer_pk)
    secondary_customer = session.get(Customer, secondary_customer_pk)
    if primary_customer is None or secondary_customer is None:
        return None

    if primary_customer.id == secondary_customer.id:
        # The two conversations already belong to the same Customer (e.g. a
        # prior merge already unified them). Nothing left to transfer;
        # return the most recent merge record for this pair if one exists,
        # otherwise treat it as a no-op success.
        existing = _get_merge_by_customer_pair(session, primary_customer.id, secondary_customer.id)
        if existing is not None:
            return CustomerMergeData(merge=existing, primary_customer=primary, secondary_customer=secondary)
        confidence, reason, matching_fields, matching_signals = (
            _duplicate_signals(primary, secondary) or (0.0, "Already the same customer", [], [])
        )
        merge = CustomerMerge(
            facebook_page_id=page_obj.id,
            primary_conversation_id=primary.id,
            secondary_conversation_id=secondary.id,
            primary_customer_id=primary_customer.id,
            secondary_customer_id=secondary_customer.id,
            merged_by_user_id=user.id,
            duplicate_confidence=confidence,
            duplicate_reason=reason,
            matching_fields=matching_fields,
            matching_signals=matching_signals,
        )
        session.add(merge)
        session.commit()
        session.refresh(merge)
        return CustomerMergeData(merge=merge, primary_customer=primary, secondary_customer=secondary)

    if secondary_customer.merged_into_customer_id is not None:
        if secondary_customer.merged_into_customer_id == primary_customer.id:
            existing = _get_merge_by_customer_pair(session, primary_customer.id, secondary_customer.id)
            if existing is not None:
                return CustomerMergeData(merge=existing, primary_customer=primary, secondary_customer=secondary)
        else:
            raise ValueError("Secondary customer has already been merged into a different primary customer")

    prior_merge = _get_merge_by_secondary_customer(session, secondary_customer.id)
    if prior_merge is not None and prior_merge.primary_customer_id != primary_customer.id:
        raise ValueError("Secondary customer has already been merged into a different primary customer")
    if prior_merge is not None and prior_merge.primary_customer_id == primary_customer.id:
        return CustomerMergeData(merge=prior_merge, primary_customer=primary, secondary_customer=secondary)

    # Check if this exact merge pair (primary, secondary) already exists — idempotency
    existing_merge = _get_merge_by_customer_pair(session, primary_customer.id, secondary_customer.id)
    if existing_merge is not None:
        # Pair already merged before; return the existing record
        return CustomerMergeData(merge=existing_merge, primary_customer=primary, secondary_customer=secondary)

    duplicate_info = _duplicate_signals(primary, secondary)
    if duplicate_info is None:
        raise ValueError("Selected customers do not have enough duplicate signals to merge safely")
    confidence, reason, matching_fields, matching_signals = duplicate_info

    now = datetime.now(UTC)

    # --- Atomically transfer ownership from secondary Customer to primary ---

    for identity in (
        session.query(CustomerIdentity)
        .filter(CustomerIdentity.customer_id == secondary_customer.id)
        .all()
    ):
        identity.customer_id = primary_customer.id
        session.add(identity)

    for conversation in (
        session.query(Conversation)
        .filter(Conversation.customer_id == secondary_customer.id)
        .all()
    ):
        conversation.customer_id = primary_customer.id
        session.add(conversation)

    for note in session.query(CustomerNote).filter(CustomerNote.customer_id == secondary_customer.id).all():
        note.customer_id = primary_customer.id
        session.add(note)

    primary_tag_ids = {
        row[0]
        for row in session.query(CustomerTagAssignment.tag_id)
        .filter(CustomerTagAssignment.customer_id == primary_customer.id)
        .all()
    }
    for assignment in (
        session.query(CustomerTagAssignment)
        .filter(CustomerTagAssignment.customer_id == secondary_customer.id)
        .all()
    ):
        if assignment.tag_id in primary_tag_ids:
            session.delete(assignment)
            continue
        assignment.customer_id = primary_customer.id
        primary_tag_ids.add(assignment.tag_id)
        session.add(assignment)

    for event in (
        session.query(CustomerTagEvent)
        .filter(CustomerTagEvent.customer_id == secondary_customer.id)
        .all()
    ):
        event.customer_id = primary_customer.id
        session.add(event)

    if primary_customer.name is None and secondary_customer.name is not None:
        primary_customer.name = secondary_customer.name
    if primary_customer.phone is None and secondary_customer.phone is not None:
        primary_customer.phone = secondary_customer.phone
    if primary_customer.email is None and secondary_customer.email is not None:
        primary_customer.email = secondary_customer.email

    if primary.customer_name is None and secondary.customer_name is not None:
        primary.customer_name = secondary.customer_name
    if primary.customer_avatar_url is None and secondary.customer_avatar_url is not None:
        primary.customer_avatar_url = secondary.customer_avatar_url

    primary_customer.updated_at = now
    secondary_customer.merged_into_customer_id = primary_customer.id
    secondary_customer.merged_at = now
    secondary_customer.updated_at = now
    primary.updated_at = now
    secondary.updated_at = now

    merge = CustomerMerge(
        facebook_page_id=page_obj.id,
        primary_conversation_id=primary.id,
        secondary_conversation_id=secondary.id,
        primary_customer_id=primary_customer.id,
        secondary_customer_id=secondary_customer.id,
        merged_by_user_id=user.id,
        duplicate_confidence=confidence,
        duplicate_reason=reason,
        matching_fields=matching_fields,
        matching_signals=matching_signals,
    )
    session.add_all([primary_customer, secondary_customer, primary, secondary, merge])

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(primary)
    session.refresh(secondary)
    session.refresh(merge)
    return CustomerMergeData(merge=merge, primary_customer=primary, secondary_customer=secondary)
