"""Pydantic schemas for customer-centric orders."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.schemas.messenger import PaginationMeta
from pydantic import BaseModel, ConfigDict, Field, model_validator


OrderStatus = Literal["draft", "confirmed", "cancelled"]
PaymentStatus = Literal["unpaid", "partial", "paid", "refunded"]
ShippingStatus = Literal["pending", "packed", "shipped", "delivered", "cancelled"]
MAX_MONEY = Decimal("9999999999.99")


class OrderItemCreate(BaseModel):
    product_uuid: str | None = None
    item_name: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=255)
    quantity: int = Field(ge=1)
    unit_price: Decimal | None = Field(default=None, ge=Decimal("0"), le=MAX_MONEY)
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_manual_or_product_item(self) -> OrderItemCreate:
        self.product_uuid = self.product_uuid.strip() if self.product_uuid else None
        self.item_name = self.item_name.strip() if self.item_name else None
        self.sku = self.sku.strip() if self.sku else None
        self.note = self.note.strip() if self.note else None
        if self.product_uuid is None:
            if self.item_name is None:
                raise ValueError("item_name is required for manual items")
            if self.unit_price is None:
                raise ValueError("unit_price is required for manual items")
        return self


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    product_uuid: str | None = None
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
    discount_amount: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=MAX_MONEY)
    shipping_fee: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=MAX_MONEY)
    shipping_address: str | None = Field(default=None, max_length=5000)
    note: str | None = Field(default=None, max_length=5000)


class OrderUpdate(BaseModel):
    status: OrderStatus | None = None
    payment_status: PaymentStatus | None = None
    shipping_status: ShippingStatus | None = None
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    discount_amount: Decimal | None = Field(default=None, ge=Decimal("0"), le=MAX_MONEY)
    shipping_fee: Decimal | None = Field(default=None, ge=Decimal("0"), le=MAX_MONEY)
    shipping_address: str | None = Field(default=None, max_length=5000)
    note: str | None = Field(default=None, max_length=5000)


class OrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    order_number: str
    customer_uuid: str
    customer_name: str | None = None
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
    item_count: int
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


class OrderOperationalSummaryResponse(BaseModel):
    all: int
    draft: int
    needs_payment: int
    needs_packing: int
    packed: int
    in_transit: int
    shipping_issue: int
    cancelled: int


class CustomerOrderSummaryResponse(BaseModel):
    order_count: int
    total_spend: str
    latest_order_at: datetime | None = None
