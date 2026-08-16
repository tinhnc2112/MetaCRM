"""Schemas for Messenger customer profiles and internal notes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from app.schemas.messenger import PaginationMeta


class CustomerProfileConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    customer_psid: str
    customer_name: str | None = None
    customer_avatar_url: str | None = None
    last_message_at: datetime | None
    unread_count: int = 0


class CustomerTagSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None = None


class CustomerTagResponse(CustomerTagSummaryResponse):
    customer_count: int = 0


class CustomerTagListResponse(BaseModel):
    items: list[CustomerTagResponse]


class CustomerTagCustomersResponse(BaseModel):
    items: list[CustomerProfileConversationResponse]
    meta: PaginationMeta


class CustomerTagAssignmentResponse(BaseModel):
    customer_id: str
    tag: CustomerTagSummaryResponse
    attached: bool


class CustomerTimelineResponse(BaseModel):
    type: Literal["message", "note", "tag"]
    timestamp: datetime
    preview: str | None = None
    content: str | None = None
    is_from_page: bool | None = None
    action: Literal["added", "removed"] | None = None
    tag_name: str | None = None
    tag_slug: str | None = None


class CustomerNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    created_at: datetime
    updated_at: datetime


class CustomerProfileResponse(BaseModel):
    conversation: CustomerProfileConversationResponse
    tags: list[CustomerTagSummaryResponse]
    timeline: list[CustomerTimelineResponse]
    notes: list[CustomerNoteResponse]


class CustomerNoteCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class CustomerNoteUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class CustomerNoteDeleteResponse(BaseModel):
    deleted: bool
    note_id: str


class CustomerTagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class CustomerTagUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class CustomerTagDeleteResponse(BaseModel):
    deleted: bool
    tag_id: int
