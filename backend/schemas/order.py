from datetime import datetime
from pydantic import BaseModel


class OrderCreate(BaseModel):
    sender_id: str
    customer_name: str | None = None
    phone: str | None = None
    address: str | None = None
    product: str | None = None
    quantity: int = 1
    note: str | None = None
    raw_message: str


class OrderRead(OrderCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
