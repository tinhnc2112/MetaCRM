from sqlalchemy.orm import Session

from models.order import Order
from schemas.order import OrderCreate, OrderRead


class OrderService:
    def __init__(self, db: Session):
        self.db = db

    def create_order(self, order_in: OrderCreate) -> Order:
        order = Order(**order_in.model_dump())
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    def create_order_from_ai(self, sender_id: str, customer_message: str, ai_result: dict) -> Order:
        order_in = OrderCreate(
            sender_id=sender_id,
            customer_name=ai_result.get("customer_name"),
            phone=ai_result.get("phone"),
            address=ai_result.get("address"),
            product=ai_result.get("product"),
            quantity=int(ai_result.get("quantity") or 1),
            note=ai_result.get("note"),
            raw_message=customer_message,
        )
        return self.create_order(order_in)

    def list_orders(self) -> list[OrderRead]:
        orders = self.db.query(Order).order_by(Order.created_at.desc()).all()
        return [OrderRead.model_validate(order) for order in orders]
