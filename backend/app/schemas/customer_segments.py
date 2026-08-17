"""Schemas for customer segments and advanced filtering."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.customers import CustomerProfileConversationResponse
from app.schemas.messenger import PaginationMeta

CustomerSegmentField = Literal[
    "TAG",
    "CUSTOMER_STATUS",
    "CONVERSATION_STATUS",
    "LAST_ACTIVITY",
    "ORDER_COUNT",
    "TOTAL_SPENT",
]

CustomerSegmentOperator = Literal[
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


class CustomerSegmentRuleRequest(BaseModel):
    field: CustomerSegmentField
    operator: CustomerSegmentOperator
    value: Any
    sort_order: int | None = Field(default=None, ge=0)


class CustomerSegmentUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    active: bool = True
    rules: list[CustomerSegmentRuleRequest] = Field(min_length=1)


class CustomerSegmentRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field: CustomerSegmentField
    operator: CustomerSegmentOperator
    value: Any
    sort_order: int


class CustomerSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    active: bool
    created_by: int
    created_at: datetime
    updated_at: datetime
    customer_count: int = 0
    rules: list[CustomerSegmentRuleResponse] = Field(default_factory=list)


class CustomerSegmentListResponse(BaseModel):
    items: list[CustomerSegmentResponse]


class CustomerSegmentCustomersResponse(BaseModel):
    items: list[CustomerProfileConversationResponse]
    meta: PaginationMeta


class CustomerSegmentPreviewResponse(CustomerSegmentCustomersResponse):
    pass


class CustomerSegmentDeleteResponse(BaseModel):
    deleted: bool
    segment_id: int
