"""Request and response schemas for authentication endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255, description="Username or email address")
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    name: str
    description: str | None


class UserResponse(BaseModel):
    """Safe user representation; deliberately excludes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    username: str
    email: str
    full_name: str | None
    avatar_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: list[RoleResponse] = []
