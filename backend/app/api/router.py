"""Top-level API router."""

from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.customer_segments import router as customer_segments_router
from app.api.customer_tags import router as customer_tags_router
from app.api.customers import router as customers_router
from app.api.facebook import router as facebook_router
from app.api.inventory import router as inventory_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.system import router as system_router
from app.api.webhook import router as webhook_router
from app.api.ws import router as websocket_router
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system_router, prefix="/system")
api_router.include_router(auth_router)
api_router.include_router(facebook_router)
api_router.include_router(customer_tags_router)
api_router.include_router(customer_segments_router)
api_router.include_router(customers_router)
api_router.include_router(orders_router)
api_router.include_router(products_router)
api_router.include_router(inventory_router)
api_router.include_router(webhook_router)
api_router.include_router(conversations_router)
api_router.include_router(websocket_router)
