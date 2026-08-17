"""Schemas for customer duplicate detection and merge workflows."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.customers import CustomerProfileConversationResponse
from app.schemas.messenger import PaginationMeta


class CustomerDuplicateCandidateResponse(BaseModel):
    primary_customer: CustomerProfileConversationResponse
    duplicate_customer: CustomerProfileConversationResponse
    confidence: float
    reason: str
    matching_fields: list[str]
    matching_signals: list[str]


class CustomerDuplicateListResponse(BaseModel):
    items: list[CustomerDuplicateCandidateResponse]
    meta: PaginationMeta


class CustomerMergeRequest(BaseModel):
    secondary_customer_id: str = Field(min_length=1)


class CustomerMergeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merge_id: int
    primary_customer: CustomerProfileConversationResponse
    secondary_customer: CustomerProfileConversationResponse
    merged_by_user_id: int | None = None
    merged_at: datetime
    duplicate_confidence: float
    duplicate_reason: str
    matching_fields: list[str]
    matching_signals: list[str]
