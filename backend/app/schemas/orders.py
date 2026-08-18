"""Pydantic schemas for customer-centric orders."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.schemas.messenger import PaginationMeta
from pydantic import BaseModel, ConfigDict, Field


OrderStatus = Literal["draft", "confirmed", "cancelled"]
PaymentStatus = Literal["unpaid", "partial", "paid", "refunded"]
ShippingStatus = Literal["pending", "packed", "shipped", "delivered", "cancelled"]


class OrderItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=255)
    quantity: int = Field(ge=1)
    unit_price: Decimal = Field(ge=Decimal("0"))
    note: str | None = Field(default=None, max_length=5000)


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    item_name: str
    sku: str | None = None
    quantity: int
    unit_price: str
    line_total: str
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class OrderCreate(BaseModel):
    customer_uuid: str = Field(min_length=1)
    conversation_uuid: str | None = None
    items: list[OrderItemCreate] = Field(min_length=1)
    status: OrderStatus = "draft"
    payment_status: PaymentStatus = "unpaid"
    shipping_status: ShippingStatus = "pending"
    currency: str = Field(default="VND", min_length=1, max_length=8)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    shipping_fee: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    shipping_address: str | None = Field(default=None, max_length=5000)
    note: str | None = Field(default=None, max_length=5000)


class OrderUpdate(BaseModel):
    status: OrderStatus | None = None
    payment_status: PaymentStatus | None = None
    shipping_status: ShippingStatus | None = None
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    discount_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    shipping_fee: Decimal | None = Field(default=None, ge=Decimal("0"))
    shipping_address: str | None = Field(default=None, max_length=5000)
    note: str | None = Field(default=None, max_length=5000)


class OrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    order_number: str
    customer_uuid: str
    customer_name_snapshot: str | None = None
    customer_phone_snapshot: str | None = None
    customer_email_snapshot: str | None = None
    conversation_uuid: str | None = None
    status: OrderStatus
    payment_status: PaymentStatus
    shipping_status: ShippingStatus
    currency: str
    subtotal_amount: str
    discount_amount: str
    shipping_fee: str
    total_amount: str
    shipping_address: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None = None


class OrderResponse(OrderListItem):
    items: list[OrderItemResponse] = Field(default_factory=list)
    deleted_at: datetime | None = None


class OrderListResponse(BaseModel):
    items: list[OrderListItem]
    meta: PaginationMeta

