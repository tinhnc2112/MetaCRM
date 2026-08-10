"""Top-level API router."""

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.facebook import router as facebook_router
from app.api.system import router as system_router
from app.api.webhook import router as webhook_router
from app.api.ws import router as websocket_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system_router, prefix="/system")
api_router.include_router(auth_router)
api_router.include_router(facebook_router)
api_router.include_router(webhook_router)
api_router.include_router(websocket_router)
