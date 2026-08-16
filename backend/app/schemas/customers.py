"""Schemas for Messenger customer profiles and internal notes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CustomerProfileConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    customer_psid: str
    customer_name: str | None = None
    customer_avatar_url: str | None = None
    last_message_at: datetime | None
    unread_count: int = 0


class CustomerTimelineResponse(BaseModel):
    type: Literal["message", "note"]
    timestamp: datetime
    preview: str | None = None
    content: str | None = None
    is_from_page: bool | None = None


class CustomerNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    created_at: datetime
    updated_at: datetime


class CustomerProfileResponse(BaseModel):
    conversation: CustomerProfileConversationResponse
    timeline: list[CustomerTimelineResponse]
    notes: list[CustomerNoteResponse]


class CustomerNoteCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class CustomerNoteUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class CustomerNoteDeleteResponse(BaseModel):
    deleted: bool
    note_id: str
