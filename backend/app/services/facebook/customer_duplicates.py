"""Customer duplicate detection and merge services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.models.auth import User
from app.models.customers import CustomerMerge, CustomerNote, CustomerTagAssignment, CustomerTagEvent
from app.models.messenger import Conversation, Message
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


def _collect_primary_tag_ids(session: Session, primary_conversation_id: int) -> set[int]:
    rows = (
        session.query(CustomerTagAssignment.tag_id)
        .filter(CustomerTagAssignment.conversation_id == primary_conversation_id)
        .all()
    )
    return {row[0] for row in rows}


def _get_existing_merge(session: Session, primary_id: int, secondary_id: int) -> CustomerMerge | None:
    return (
        session.query(CustomerMerge)
        .filter(
            CustomerMerge.primary_conversation_id == primary_id,
            CustomerMerge.secondary_conversation_id == secondary_id,
        )
        .first()
    )


def _get_merge_by_secondary(session: Session, secondary_id: int) -> CustomerMerge | None:
    return (
        session.query(CustomerMerge)
        .filter(CustomerMerge.secondary_conversation_id == secondary_id)
        .order_by(CustomerMerge.created_at.desc(), CustomerMerge.id.desc())
        .first()
    )


def merge_customers(
    session: Session,
    user: User,
    primary_customer_id: str,
    secondary_customer_id: str,
) -> CustomerMergeData | None:
    page_obj = _current_page(session, user)
    if page_obj is None:
        return None

    primary = _conversation_for_page(session, page_obj.id, primary_customer_id)
    secondary = _conversation_for_page(session, page_obj.id, secondary_customer_id, include_deleted=True)
    if primary is None or secondary is None:
        return None

    if primary.id == secondary.id:
        raise ValueError("Cannot merge a customer into itself")

    existing = _get_existing_merge(session, primary.id, secondary.id)
    if existing is not None:
        return CustomerMergeData(merge=existing, primary_customer=primary, secondary_customer=secondary)

    if secondary.deleted_at is not None:
        prior_merge = _get_merge_by_secondary(session, secondary.id)
        if prior_merge is not None and prior_merge.primary_conversation_id == primary.id:
            return CustomerMergeData(merge=prior_merge, primary_customer=primary, secondary_customer=secondary)
        if prior_merge is not None:
            raise ValueError("Secondary customer has already been merged into a different primary customer")

    prior_merge = _get_merge_by_secondary(session, secondary.id)
    if prior_merge is not None and prior_merge.primary_conversation_id != primary.id:
        raise ValueError("Secondary customer has already been merged into a different primary customer")

    duplicate_info = _duplicate_signals(primary, secondary)
    if duplicate_info is None:
        raise ValueError("Selected customers do not have enough duplicate signals to merge safely")
    confidence, reason, matching_fields, matching_signals = duplicate_info

    now = datetime.now(UTC)
    primary_tag_ids = _collect_primary_tag_ids(session, primary.id)

    for note in session.query(CustomerNote).filter(CustomerNote.conversation_id == secondary.id).all():
        note.conversation_id = primary.id
        session.add(note)

    for message in session.query(Message).filter(Message.conversation_id == secondary.id).all():
        message.conversation_id = primary.id
        session.add(message)

    for event in session.query(CustomerTagEvent).filter(CustomerTagEvent.conversation_id == secondary.id).all():
        event.conversation_id = primary.id
        session.add(event)

    for assignment in (
        session.query(CustomerTagAssignment)
        .filter(CustomerTagAssignment.conversation_id == secondary.id)
        .all()
    ):
        if assignment.tag_id in primary_tag_ids:
            session.delete(assignment)
            continue
        assignment.conversation_id = primary.id
        primary_tag_ids.add(assignment.tag_id)
        session.add(assignment)

    if primary.customer_name is None and secondary.customer_name is not None:
        primary.customer_name = secondary.customer_name
    if primary.customer_avatar_url is None and secondary.customer_avatar_url is not None:
        primary.customer_avatar_url = secondary.customer_avatar_url
    if primary.last_message_at is None or (secondary.last_message_at and secondary.last_message_at > primary.last_message_at):
        primary.last_message_at = secondary.last_message_at
    if primary.last_read_at is None or (secondary.last_read_at and secondary.last_read_at > primary.last_read_at):
        primary.last_read_at = secondary.last_read_at

    primary.updated_at = now
    secondary.deleted_at = now
    secondary.merged_into_conversation_id = primary.id
    secondary.merged_at = now
    secondary.updated_at = now

    merge = CustomerMerge(
        facebook_page_id=page_obj.id,
        primary_conversation_id=primary.id,
        secondary_conversation_id=secondary.id,
        merged_by_user_id=user.id,
        duplicate_confidence=confidence,
        duplicate_reason=reason,
        matching_fields=matching_fields,
        matching_signals=matching_signals,
    )
    session.add_all([primary, secondary, merge])

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(primary)
    session.refresh(secondary)
    session.refresh(merge)
    return CustomerMergeData(merge=merge, primary_customer=primary, secondary_customer=secondary)
