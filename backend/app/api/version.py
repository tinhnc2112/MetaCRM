"""Backward-compatible runtime version endpoint."""

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

router = APIRouter(tags=["version"])


class VersionResponse(BaseModel):
    name: str
    version: str
    environment: str


@router.get("/version", response_model=VersionResponse, status_code=status.HTTP_200_OK)
def version(request: Request) -> VersionResponse:
    """Return safe runtime release metadata."""
    settings = request.app.state.settings
    return VersionResponse(name=settings.app_name, version=settings.app_version, environment=settings.environment)
