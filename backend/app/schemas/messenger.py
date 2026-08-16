"""Pydantic schemas for Messenger webhook responses and CRM read API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WebhookAcceptedResponse(BaseModel):
    received: bool = True
    events_processed: int


class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    page_id: str
    psid: str
    customer_name: str | None
    customer_avatar_url: str | None = None
    last_message_at: datetime | None
    last_message_preview: str | None = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    meta: PaginationMeta


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sender_psid: str | None = None
    recipient_page_id: str
    mid: str
    event_type: str
    is_from_page: bool
    text: str | None
    attachments: list[dict] | None = None
    postback_payload: str | None
    fb_timestamp_ms: int | None
    sent_at: datetime | None
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    meta: PaginationMeta


class MarkConversationReadResponse(BaseModel):
    conversation_id: str
    last_read_at: datetime | None
    unread_count: int
    already_read: bool


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
