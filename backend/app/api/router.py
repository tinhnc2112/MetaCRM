"""Top-level API router."""

from fastapi import APIRouter

from app.api.system import router as system_router
from app.api.auth import router as auth_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(auth_router, prefix="/api/v1")
