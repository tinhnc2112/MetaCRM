"""Customer segment storage and evaluation services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Sequence

from app.models.auth import User
from app.models.customers import (
    CustomerSegment,
    CustomerSegmentRule,
    CustomerTag,
    CustomerTagAssignment,
)
from app.models.messenger import Conversation
from app.services.facebook.conversations import PaginatedResult, unread_count_for_conversation
from app.services.facebook.pages import get_current_page
from sqlalchemy.orm import Session, selectinload

CustomerSegmentFieldName = Literal[
    "TAG",
    "CUSTOMER_STATUS",
    "CONVERSATION_STATUS",
    "LAST_ACTIVITY",
    "ORDER_COUNT",
    "TOTAL_SPENT",
]

CustomerSegmentOperatorName = Literal[
    "equals",
    "not_equals",
    "contains",
    "greater_than",
    "less_than",
    "greater_or_equal",
    "less_or_equal",
    "before",
    "after",
]

STRING_FIELDS = {"TAG", "CUSTOMER_STATUS", "CONVERSATION_STATUS"}
DATE_FIELDS = {"LAST_ACTIVITY"}
NUMERIC_FIELDS = {"ORDER_COUNT", "TOTAL_SPENT"}
STRING_OPERATORS = {"equals", "not_equals", "contains"}
DATE_OPERATORS = {
    "equals",
    "not_equals",
    "greater_than",
    "less_than",
    "greater_or_equal",
    "less_or_equal",
    "before",
    "after",
}
NUMERIC_OPERATORS = {
    "equals",
    "not_equals",
    "greater_than",
    "less_than",
    "greater_or_equal",
    "less_or_equal",
}


@dataclass(frozen=True)
class CustomerSegmentRuleSpec:
    field: str
    operator: str
    value: Any
    sort_order: int


@dataclass(frozen=True)
class CustomerSegmentRuleData:
    id: int
    field: str
    operator: str
    value: Any
    sort_order: int


@dataclass(frozen=True)
class CustomerSegmentData:
    id: int
    name: str
    description: str | None
    active: bool
    created_by: int
    created_at: datetime
    updated_at: datetime
    rules: list[CustomerSegmentRuleData]
    customer_count: int = 0


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _current_page(session: Session, user: User):
    return get_current_page(session, user)


def _segment_data(segment: CustomerSegment, customer_count: int = 0) -> CustomerSegmentData:
    rules = [
        CustomerSegmentRuleData(
            id=rule.id,
            field=rule.field,
            operator=rule.operator,
            value=rule.value,
            sort_order=rule.sort_order,
        )
        for rule in sorted(segment.rules, key=lambda item: (item.sort_order, item.id))
    ]
    return CustomerSegmentData(
        id=segment.id,
        name=segment.name,
        description=segment.description,
        active=segment.active,
        created_by=segment.created_by,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
        rules=rules,
        customer_count=customer_count,
    )


def _rule_attr(rule: object, key: str, default: Any = None) -> Any:
    if isinstance(rule, dict):
        return rule.get(key, default)
    return getattr(rule, key, default)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _utc(value) or value
    if isinstance(value, str):
        cleaned = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        return _utc(parsed) or parsed
    raise ValueError("Date rules must use an ISO 8601 datetime value")


def _normalize_numeric_value(value: Any) -> int | float:
    if isinstance(value, bool):
        raise ValueError("Numeric rules must use a number")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Numeric rules must use a number")
        try:
            if "." in cleaned:
                return float(cleaned)
            return int(cleaned)
        except ValueError as exc:
            raise ValueError("Numeric rules must use a number") from exc
    raise ValueError("Numeric rules must use a number")


def _normalize_string_value(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("String rules must use text")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("String rules must not be empty")
    return cleaned


def _normalize_rule_spec(rule: object, index: int) -> CustomerSegmentRuleSpec:
    field = str(_rule_attr(rule, "field", "")).strip().upper()
    operator = str(_rule_attr(rule, "operator", "")).strip().lower()
    sort_order = _rule_attr(rule, "sort_order", None)
    value = _rule_attr(rule, "value")

    if not field:
        raise ValueError("Rule field is required")
    if not operator:
        raise ValueError("Rule operator is required")

    if field not in STRING_FIELDS | DATE_FIELDS | NUMERIC_FIELDS:
        raise ValueError("Unsupported rule field")

    if field in STRING_FIELDS and operator not in STRING_OPERATORS:
        raise ValueError("Unsupported operator for string rules")
    if field in DATE_FIELDS and operator not in DATE_OPERATORS:
        raise ValueError("Unsupported operator for date rules")
    if field in NUMERIC_FIELDS and operator not in NUMERIC_OPERATORS:
        raise ValueError("Unsupported operator for numeric rules")

    if field in STRING_FIELDS:
        normalized_value = _normalize_string_value(value)
        if field == "CUSTOMER_STATUS":
            normalized_value = normalized_value.lower()
        elif field == "CONVERSATION_STATUS":
            normalized_value = normalized_value.lower()
    elif field in DATE_FIELDS:
        normalized_value = _parse_datetime(value).isoformat()
    else:
        normalized_value = _normalize_numeric_value(value)

    resolved_sort_order = index if sort_order is None else int(sort_order)
    return CustomerSegmentRuleSpec(
        field=field,
        operator=operator,
        value=normalized_value,
        sort_order=resolved_sort_order,
    )


def _normalize_rule_specs(rules: Sequence[object]) -> list[CustomerSegmentRuleSpec]:
    normalized = [_normalize_rule_spec(rule, index) for index, rule in enumerate(rules)]
    normalized.sort(key=lambda item: item.sort_order)
    for index, rule in enumerate(normalized):
        if rule.sort_order != index:
            normalized[index] = CustomerSegmentRuleSpec(
                field=rule.field,
                operator=rule.operator,
                value=rule.value,
                sort_order=index,
            )
    return normalized


def _customer_status(conversation: Conversation) -> str:
    last_activity = _utc(conversation.last_message_at or conversation.created_at)
    if conversation.last_message_at is None and conversation.updated_at == conversation.created_at:
        return "new"
    if last_activity is None:
        return "new"
    if datetime.now(UTC) - last_activity <= timedelta(days=30):
        return "active"
    return "inactive"


def _conversation_status(session: Session, conversation: Conversation) -> str:
    return "open" if unread_count_for_conversation(session, conversation) > 0 else "closed"


def _last_activity(conversation: Conversation) -> datetime | None:
    return _utc(conversation.last_message_at or conversation.created_at)


def _conversation_tag_values(session: Session, conversation: Conversation) -> set[str]:
    values: set[str] = set()
    committed_tags = (
        session.query(CustomerTag)
        .join(CustomerTagAssignment, CustomerTagAssignment.tag_id == CustomerTag.id)
        .filter(
            CustomerTagAssignment.conversation_id == conversation.id,
            CustomerTag.facebook_page_id == conversation.facebook_page_id,
        )
        .all()
    )
    for tag in committed_tags:
        if tag.name:
            values.add(tag.name.strip().lower())
        if tag.slug:
            values.add(tag.slug.strip().lower())
    return values


def _evaluate_string_rule(actual: str, operator: str, expected: str) -> bool:
    actual_value = actual.strip().lower()
    expected_value = expected.strip().lower()
    if operator == "equals":
        return actual_value == expected_value
    if operator == "not_equals":
        return actual_value != expected_value
    if operator == "contains":
        return expected_value in actual_value
    raise ValueError("Unsupported string operator")


def _evaluate_numeric_rule(actual: int | float | None, operator: str, expected: int | float) -> bool:
    if actual is None:
        return False
    left = float(actual)
    right = float(expected)
    if operator == "equals":
        return left == right
    if operator == "not_equals":
        return left != right
    if operator == "greater_than":
        return left > right
    if operator == "less_than":
        return left < right
    if operator == "greater_or_equal":
        return left >= right
    if operator == "less_or_equal":
        return left <= right
    raise ValueError("Unsupported numeric operator")


def _evaluate_date_rule(actual: datetime | None, operator: str, expected: str) -> bool:
    if actual is None:
        return False
    actual_value = _utc(actual)
    expected_value = _parse_datetime(expected)
    if actual_value is None:
        return False
    if operator == "equals":
        return actual_value == expected_value
    if operator == "not_equals":
        return actual_value != expected_value
    if operator in {"greater_than", "after"}:
        return actual_value > expected_value
    if operator in {"less_than", "before"}:
        return actual_value < expected_value
    if operator == "greater_or_equal":
        return actual_value >= expected_value
    if operator == "less_or_equal":
        return actual_value <= expected_value
    raise ValueError("Unsupported date operator")


def _rule_matches(session: Session, conversation: Conversation, rule: CustomerSegmentRuleSpec) -> bool:
    if rule.field == "TAG":
        values = _conversation_tag_values(session, conversation)
        if rule.operator == "equals":
            return rule.value.strip().lower() in values
        if rule.operator == "not_equals":
            return rule.value.strip().lower() not in values
        if rule.operator == "contains":
            needle = rule.value.strip().lower()
            return any(needle in value for value in values)
        return False

    if rule.field == "CUSTOMER_STATUS":
        return _evaluate_string_rule(_customer_status(conversation), rule.operator, str(rule.value))

    if rule.field == "CONVERSATION_STATUS":
        return _evaluate_string_rule(_conversation_status(session, conversation), rule.operator, str(rule.value))

    if rule.field == "LAST_ACTIVITY":
        return _evaluate_date_rule(_last_activity(conversation), rule.operator, str(rule.value))

    if rule.field in NUMERIC_FIELDS:
        return False

    return False


def _matching_conversations(session: Session, page_id: int, rules: Sequence[CustomerSegmentRuleSpec]) -> list[Conversation]:
    conversations = (
        session.query(Conversation)
        .filter(Conversation.facebook_page_id == page_id, Conversation.deleted_at.is_(None))
        .order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.created_at.desc(),
            Conversation.id.desc(),
        )
        .all()
    )
    if not rules:
        return conversations
    matches: list[Conversation] = []
    for conversation in conversations:
        if all(_rule_matches(session, conversation, rule) for rule in rules):
            matches.append(conversation)
    return matches


def _segment_for_page(session: Session, page_id: int, segment_id: int) -> CustomerSegment | None:
    return (
        session.query(CustomerSegment)
        .options(selectinload(CustomerSegment.rules))
        .filter(CustomerSegment.id == segment_id, CustomerSegment.facebook_page_id == page_id)
        .first()
    )


def _segment_count(session: Session, page_id: int, rules: Sequence[CustomerSegmentRuleSpec]) -> int:
    return len(_matching_conversations(session, page_id, rules))


def _segment_from_model(segment: CustomerSegment, customer_count: int) -> CustomerSegmentData:
    rule_data = [
        CustomerSegmentRuleData(
            id=rule.id,
            field=rule.field,
            operator=rule.operator,
            value=rule.value,
            sort_order=rule.sort_order,
        )
        for rule in sorted(segment.rules, key=lambda item: (item.sort_order, item.id))
    ]
    return CustomerSegmentData(
        id=segment.id,
        name=segment.name,
        description=segment.description,
        active=segment.active,
        created_by=segment.created_by,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
        rules=rule_data,
        customer_count=customer_count,
    )


def _prepare_segment_payload(
    name: str,
    description: str | None,
    active: bool,
    rules: Sequence[object],
) -> tuple[str, str | None, bool, list[CustomerSegmentRuleSpec]]:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Segment name must not be empty")
    cleaned_description = description.strip() if description and description.strip() else None
    normalized_rules = _normalize_rule_specs(rules)
    if not normalized_rules:
        raise ValueError("At least one rule is required")
    return cleaned_name, cleaned_description, active, normalized_rules


def list_customer_segments(session: Session, user: User) -> list[CustomerSegmentData] | None:
    page = _current_page(session, user)
    if page is None:
        return None

    segments = (
        session.query(CustomerSegment)
        .options(selectinload(CustomerSegment.rules))
        .filter(CustomerSegment.facebook_page_id == page.id)
        .order_by(CustomerSegment.active.desc(), CustomerSegment.name.asc(), CustomerSegment.id.asc())
        .all()
    )
    results: list[CustomerSegmentData] = []
    for segment in segments:
        rules = [
            CustomerSegmentRuleSpec(
                field=rule.field,
                operator=rule.operator,
                value=rule.value,
                sort_order=rule.sort_order,
            )
            for rule in sorted(segment.rules, key=lambda item: (item.sort_order, item.id))
        ]
        results.append(_segment_from_model(segment, _segment_count(session, page.id, rules)))
    return results


def get_customer_segment_for_user(session: Session, user: User, segment_id: int) -> CustomerSegment | None:
    page = _current_page(session, user)
    if page is None:
        return None
    return _segment_for_page(session, page.id, segment_id)


def create_customer_segment(
    session: Session,
    user: User,
    name: str,
    description: str | None,
    active: bool,
    rules: Sequence[object],
) -> CustomerSegmentData | None:
    page = _current_page(session, user)
    if page is None:
        return None

    cleaned_name, cleaned_description, active, normalized_rules = _prepare_segment_payload(
        name, description, active, rules
    )
    segment = CustomerSegment(
        facebook_page_id=page.id,
        name=cleaned_name,
        description=cleaned_description,
        active=active,
        created_by=user.id,
    )
    for rule in normalized_rules:
        segment.rules.append(
            CustomerSegmentRule(
                field=rule.field,
                operator=rule.operator,
                value=rule.value,
                sort_order=rule.sort_order,
            )
        )
    session.add(segment)
    session.commit()
    session.refresh(segment)
    return _segment_from_model(segment, _segment_count(session, page.id, normalized_rules))


def update_customer_segment(
    session: Session,
    user: User,
    segment_id: int,
    name: str,
    description: str | None,
    active: bool,
    rules: Sequence[object],
) -> CustomerSegmentData | None:
    segment = get_customer_segment_for_user(session, user, segment_id)
    if segment is None:
        return None

    cleaned_name, cleaned_description, active, normalized_rules = _prepare_segment_payload(
        name, description, active, rules
    )
    segment.name = cleaned_name
    segment.description = cleaned_description
    segment.active = active
    segment.rules = [
        CustomerSegmentRule(
            field=rule.field,
            operator=rule.operator,
            value=rule.value,
            sort_order=rule.sort_order,
        )
        for rule in normalized_rules
    ]
    session.add(segment)
    session.commit()
    session.refresh(segment)
    page = _current_page(session, user)
    customer_count = _segment_count(session, page.id if page else segment.facebook_page_id, normalized_rules)
    return _segment_from_model(segment, customer_count)


def delete_customer_segment(session: Session, user: User, segment_id: int) -> CustomerSegmentData | None:
    segment = get_customer_segment_for_user(session, user, segment_id)
    if segment is None:
        return None

    page = _current_page(session, user)
    normalized_rules = [
        CustomerSegmentRuleSpec(
            field=rule.field,
            operator=rule.operator,
            value=rule.value,
            sort_order=rule.sort_order,
        )
        for rule in sorted(segment.rules, key=lambda item: (item.sort_order, item.id))
    ]
    data = _segment_from_model(segment, _segment_count(session, page.id if page else segment.facebook_page_id, normalized_rules))
    session.delete(segment)
    session.commit()
    return data


def preview_customer_segment_definition(
    session: Session,
    user: User,
    name: str,
    description: str | None,
    active: bool,
    rules: Sequence[object],
    *,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResult[Conversation] | None:
    current_page = _current_page(session, user)
    if current_page is None:
        return None
    _, _, _, normalized_rules = _prepare_segment_payload(name, description, active, rules)
    page_size = min(page_size, 100)
    page = max(page, 1)
    matches = _matching_conversations(session, current_page.id, normalized_rules)
    total = len(matches)
    items = matches[(page - 1) * page_size : (page - 1) * page_size + page_size]
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def preview_customer_segment(
    session: Session,
    user: User,
    segment_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResult[Conversation] | None:
    segment = get_customer_segment_for_user(session, user, segment_id)
    if segment is None:
        return None
    page_size = min(page_size, 100)
    page = max(page, 1)
    normalized_rules = [
        CustomerSegmentRuleSpec(
            field=rule.field,
            operator=rule.operator,
            value=rule.value,
            sort_order=rule.sort_order,
        )
        for rule in sorted(segment.rules, key=lambda item: (item.sort_order, item.id))
    ]
    matches = _matching_conversations(session, segment.facebook_page_id, normalized_rules)
    total = len(matches)
    items = matches[(page - 1) * page_size : (page - 1) * page_size + page_size]
    return PaginatedResult(items=items, total=total, page=page, page_size=page_size)


def list_customer_segment_customers(
    session: Session,
    user: User,
    segment_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResult[Conversation] | None:
    return preview_customer_segment(session, user, segment_id, page=page, page_size=page_size)
