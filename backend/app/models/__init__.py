"""SQLAlchemy model package. Import models here for Alembic discovery."""

from app.db.base import Base
from app.models.auth import Role, User, user_roles
from app.models.base import AuditMixin, BaseModel, SoftDeleteMixin, UTCDateTimeMixin, UUIDMixin
from app.models.customer_core import Customer, CustomerIdentity
from app.models.customers import (
    CustomerMerge,
    CustomerNote,
    CustomerSegment,
    CustomerSegmentRule,
    CustomerTag,
    CustomerTagAssignment,
    CustomerTagEvent,
)
from app.models.facebook import FacebookAccount, FacebookOAuthState, FacebookPage, UserPageContext
from app.models.inventory import ProductInventory, StockMovement
from app.models.messenger import Conversation, Message
from app.models.orders import Order, OrderEvent, OrderItem
from app.models.products import Product
from app.models.shipments import Shipment, ShipmentEvent

__all__ = [
    "AuditMixin",
    "Base",
    "BaseModel",
    "Conversation",
    "Customer",
    "CustomerIdentity",
    "CustomerNote",
    "CustomerMerge",
    "CustomerSegment",
    "CustomerSegmentRule",
    "CustomerTag",
    "CustomerTagAssignment",
    "CustomerTagEvent",
    "FacebookAccount",
    "FacebookOAuthState",
    "FacebookPage",
    "Message",
    "ProductInventory",
    "Order",
    "OrderEvent",
    "OrderItem",
    "Product",
    "Role",
    "Shipment",
    "ShipmentEvent",
    "StockMovement",
    "SoftDeleteMixin",
    "UTCDateTimeMixin",
    "UUIDMixin",
    "User",
    "UserPageContext",
    "user_roles",
]
