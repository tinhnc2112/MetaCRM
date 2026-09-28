"""Schemas for Messenger customer profiles and internal notes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.messenger import PaginationMeta
from app.utils.phone import normalize_phone
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CustomerDefaultShippingAddress(BaseModel):
    address_line: str | None = Field(default=None, max_length=5000)
    ward: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=255)
    province: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=32)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    note: str | None = Field(default=None, max_length=5000)

    @field_validator(
        "address_line", "ward", "district", "province", "postal_code", "note", mode="before"
    )
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("country_code", mode="before")
    @classmethod
    def normalize_country(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip().upper()
        if value and (len(value) != 2 or not value.isalpha() or not value.isascii()):
            raise ValueError("country_code must be a 2-letter code")
        return value or None


class CustomerContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    default_shipping_address: CustomerDefaultShippingAddress | None = None

    @field_validator("name", "phone", "email", mode="before")
    @classmethod
    def trim_contact(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None:
            normalize_phone(value)
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None:
            local, sep, domain = value.partition("@")
            if (not sep or not local or not domain or "@" in domain
                    or any(c.isspace() for c in value)):
                raise ValueError("email has an invalid format")
        return value


class CustomerProfileConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    customer_psid: str
    customer_name: str | None = None
    customer_avatar_url: str | None = None
    last_message_at: datetime | None
    unread_count: int = 0


class CustomerSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    default_shipping_address: CustomerDefaultShippingAddress | None = None
    avatar_url: str | None = None
    last_message_at: datetime | None = None
    conversation_count: int = 0
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


class CustomerListItemResponse(CustomerSummaryResponse):
    tags: list[CustomerTagSummaryResponse] = Field(default_factory=list)


class CustomerListResponse(BaseModel):
    items: list[CustomerListItemResponse]
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
    customer: CustomerSummaryResponse | None = None
    conversation: CustomerProfileConversationResponse
    conversations: list[CustomerProfileConversationResponse] = Field(default_factory=list)
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
