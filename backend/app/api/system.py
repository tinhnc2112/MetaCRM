"""System endpoints intended for platform monitoring."""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.db.init_db import check_database_connection

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str


class VersionResponse(BaseModel):
    name: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health() -> HealthResponse:
    """Return process liveness without requiring downstream dependencies."""
    return HealthResponse(status="ok")


@router.get("/health/database", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def database_health() -> HealthResponse:
    """Verify the configured MySQL connection without modifying database state."""
    try:
        check_database_connection()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable") from exc
    return HealthResponse(status="ok")


@router.get("/version", response_model=VersionResponse, status_code=status.HTTP_200_OK)
def version(request: Request) -> VersionResponse:
    """Return safe runtime release metadata."""
    settings = request.app.state.settings
    return VersionResponse(name=settings.app_name, version=settings.app_version, environment=settings.environment)
