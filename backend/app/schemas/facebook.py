"""Facebook API response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FacebookAuthUrlResponse(BaseModel):
    url: str


class FacebookPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    page_id: str
    name: str
    username: str | None
    picture_url: str | None
    is_active: bool


class FacebookPageListResponse(BaseModel):
    items: list[FacebookPageResponse]


class CurrentFacebookPageResponse(BaseModel):
    item: FacebookPageResponse | None
