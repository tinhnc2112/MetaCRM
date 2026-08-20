"""Pydantic schemas for customer-centric orders."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.schemas.messenger import PaginationMeta
from app.utils.phone import normalize_phone
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OrderStatus = Literal["draft", "confirmed", "cancelled"]
PaymentStatus = Literal["unpaid", "partial", "paid", "refunded"]
ShippingStatus = Literal["pending", "packed", "shipped", "delivered", "cancelled"]
MAX_MONEY = Decimal("9999999999.99")


class ShippingDestinationInput(BaseModel):
    recipient_name: str | None = Field(default=None, max_length=255)
    recipient_phone: str | None = Field(default=None, max_length=32)
    address_line: str | None = Field(default=None, max_length=5000)
    ward: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=255)
    province: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=32)
    country_code: str | None = Field(default="VN", min_length=2, max_length=2)
    note: str | None = Field(default=None, max_length=5000)

    @field_validator(
        "recipient_name",
        "recipient_phone",
        "address_line",
        "ward",
        "district",
        "province",
        "postal_code",
        "note",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("country_code", mode="before")
    @classmethod
    def normalize_country_code(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper() or None
        if normalized is not None and (
            len(normalized) != 2
            or any(character < "A" or character > "Z" for character in normalized)
        ):
            raise ValueError("country_code must be a 2-letter code")
        return normalized

    @model_validator(mode="after")
    def validate_phone(self) -> ShippingDestinationInput:
        if self.recipient_phone is not None:
            normalize_phone(
                self.recipient_phone,
                country_code=self.country_code or "VN",
            )
        return self


class ShippingDestinationResponse(BaseModel):
    recipient_name: str | None = None
    recipient_phone: str | None = None
    address_line: str | None = None
    ward: str | None = None
    district: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country_code: str = "VN"
    note: str | None = None
    is_complete: bool


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
    shipping_destination: ShippingDestinationInput | None = None
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def reject_ambiguous_shipping_input(self) -> OrderCreate:
        if self.shipping_address is not None and self.shipping_destination is not None:
            raise ValueError("Use either shipping_address or shipping_destination, not both")
        return self


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
    shipping_destination: ShippingDestinationResponse | None = None
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


class OrderTimelineActor(BaseModel):
    name: str | None = None
    email: str | None = None


class OrderEventTimelineItem(BaseModel):
    kind: Literal["order_event"] = "order_event"
    public_id: str
    event_type: Literal[
        "ORDER_CREATED",
        "ORDER_CONFIRMED",
        "ORDER_CANCELLED",
        "PAYMENT_STATUS_CHANGED",
        "SHIPPING_STATUS_CHANGED",
    ]
    from_value: str | None = None
    to_value: str | None = None
    details: dict | None = None
    actor: OrderTimelineActor | None = None
    created_at: datetime


class InventoryMovementTimelineItem(BaseModel):
    kind: Literal["inventory_movement"] = "inventory_movement"
    public_id: str
    movement_type: Literal["ORDER_OUT", "ORDER_CANCEL_RESTORE"]
    product_name: str
    sku: str | None = None
    quantity_delta: int
    quantity_before: int
    quantity_after: int
    actor: OrderTimelineActor | None = None
    created_at: datetime


class ShipmentEventTimelineItem(BaseModel):
    kind: Literal["shipment_event"] = "shipment_event"
    public_id: str
    shipment_uuid: str
    shipment_number: str
    event_type: Literal[
        "CREATED",
        "PACKED",
        "SHIPPED",
        "DELIVERED",
        "CANCELLED",
        "TRACKING_UPDATED",
    ]
    from_value: str | None = None
    to_value: str | None = None
    details: dict | None = None
    actor: OrderTimelineActor | None = None
    created_at: datetime


class OrderTimelineResponse(BaseModel):
    items: list[OrderEventTimelineItem | InventoryMovementTimelineItem | ShipmentEventTimelineItem]


class CustomerOrderSummaryResponse(BaseModel):
    order_count: int
    total_spend: str
    latest_order_at: datetime | None = None
