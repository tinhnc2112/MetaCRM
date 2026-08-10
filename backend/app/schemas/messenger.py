"""Pydantic schemas for Messenger webhook responses and CRM read API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


class WebhookAcceptedResponse(BaseModel):
    """Returned after successfully processing a webhook POST."""

    received: bool = True
    events_processed: int


# ---------------------------------------------------------------------------
# Pagination envelope
# ---------------------------------------------------------------------------


class PaginationMeta(BaseModel):
    """Pagination metadata included in list responses."""

    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class ConversationResponse(BaseModel):
    """Single conversation item returned by the list/detail endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    page_id: str
    psid: str
    customer_name: str | None
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """Paginated list of conversations."""

    items: list[ConversationResponse]
    meta: PaginationMeta


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """Single message item returned by the messages endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    mid: str
    event_type: str
    is_from_page: bool
    text: str | None
    postback_payload: str | None
    fb_timestamp_ms: int | None
    sent_at: datetime | None
    created_at: datetime


class MessageListResponse(BaseModel):
    """Paginated list of messages within a conversation."""

    items: list[MessageResponse]
    meta: PaginationMeta
