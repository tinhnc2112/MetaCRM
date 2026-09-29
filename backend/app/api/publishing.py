"""Scheduled Page publishing management API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user, require_admin
from app.models.auth import User
from app.models.facebook import FacebookPage
from app.models.publishing import ScheduledPost, SheetPublishingConfig
from app.services.facebook.conversations import get_user_page_ids
from app.services.publishing.sheet import SheetError
from app.services.publishing.sync import get_config, sync_sheet
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/publishing", tags=["publishing"])


class ConfigInput(BaseModel):
    spreadsheet_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")
    worksheet: str = Field(min_length=1, max_length=255)
    timezone: str = Field(min_length=1, max_length=64)


class ScheduleInput(BaseModel):
    scheduled_for_utc: datetime


class ResolutionInput(BaseModel):
    outcome: Literal["published", "verified_not_published"]
    facebook_post_id: str | None = Field(default=None, max_length=128)
    confirmed: bool


def _admin(user: User) -> bool:
    return any(role.is_active and role.name == "admin" for role in user.roles)


def _accessible(session: Session, user: User, post: ScheduledPost) -> bool:
    return _admin(user) or (
        post.facebook_page_id is not None
        and post.facebook_page_id in get_user_page_ids(session, user)
    )


def _post(session: Session, user: User, post_id: UUID) -> ScheduledPost:
    post = session.scalar(
        select(ScheduledPost).where(ScheduledPost.uuid == post_id).with_for_update()
    )
    if post is None or not _accessible(session, user, post):
        raise HTTPException(404, "Scheduled post not found")
    return post


def _serialize(session: Session, post: ScheduledPost) -> dict:
    page = session.get(FacebookPage, post.facebook_page_id) if post.facebook_page_id else None
    return {
        "id": str(post.uuid),
        "external_id": post.external_id,
        "spreadsheet_id": post.spreadsheet_id,
        "worksheet": post.worksheet,
        "source_row": post.source_row,
        "page_id": page.page_id if page else None,
        "page_name": page.name if page else None,
        "caption": post.caption,
        "image_url": post.image_url,
        "scheduled_for_utc": post.scheduled_for_utc.replace(tzinfo=UTC).isoformat()
        if post.scheduled_for_utc
        else None,
        "source_timezone": post.source_timezone,
        "status": post.status,
        "attempt_count": post.attempt_count,
        "facebook_post_id": post.facebook_post_id,
        "last_error_code": post.last_error_code,
        "last_error_message": post.last_error_message,
        "writeback_error": post.writeback_error,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
    }


@router.get("/config")
def read_config(
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_active_user)],
) -> dict:
    config = get_config(session)
    return {
        "configured": config is not None,
        "spreadsheet_id": config.spreadsheet_id if config else None,
        "worksheet": config.worksheet if config else None,
        "timezone": config.timezone if config else None,
        "last_synced_at": (
            config.last_synced_at.replace(tzinfo=UTC).isoformat()
            if config and config.last_synced_at else None
        ),
        "last_sync_error": config.last_sync_error if config else None,
        "last_sync_result": json.loads(config.last_sync_result)
        if config and config.last_sync_result
        else None,
    }


@router.put("/config")
def write_config(
    payload: ConfigInput,
    session: Annotated[Session, Depends(get_db_session)],
    _user: Annotated[User, Depends(require_admin)],
) -> dict:
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(422, "Invalid IANA timezone") from exc
    config = get_config(session)
    if config is None:
        config = SheetPublishingConfig(id=1, **payload.model_dump())
        session.add(config)
    else:
        config.spreadsheet_id, config.worksheet, config.timezone = (
            payload.spreadsheet_id,
            payload.worksheet,
            payload.timezone,
        )
    session.commit()
    return {"configured": True}


@router.post("/sync")
def sync_endpoint(
    session: Annotated[Session, Depends(get_db_session)],
    _user: Annotated[User, Depends(require_admin)],
) -> dict:
    try:
        return sync_sheet(session)
    except (SheetError, ValueError) as exc:
        session.rollback()
        config = get_config(session)
        if config:
            config.last_sync_error = str(exc)[:500]
            session.commit()
        raise HTTPException(502, str(exc)) from exc


@router.get("/posts")
def list_posts(
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_active_user)],
    page_id: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    query = select(ScheduledPost)
    if not _admin(user):
        query = query.where(ScheduledPost.facebook_page_id.in_(get_user_page_ids(session, user)))
    if page_id:
        query = query.join(FacebookPage).where(FacebookPage.page_id == page_id)
    if status:
        query = query.where(ScheduledPost.status == status)
    posts = session.scalars(
        query.order_by(ScheduledPost.scheduled_for_utc, ScheduledPost.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {"items": [_serialize(session, post) for post in posts]}


@router.get("/posts/{post_id}")
def get_post(
    post_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_active_user)],
) -> dict:
    return _serialize(session, _post(session, user, post_id))


@router.post("/posts/{post_id}/reschedule")
def reschedule(
    post_id: UUID,
    payload: ScheduleInput,
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_active_user)],
) -> dict:
    post = _post(session, user, post_id)
    if post.status not in {"READY", "SCHEDULED"}:
        raise HTTPException(409, "Post is not mutable")
    if payload.scheduled_for_utc.tzinfo is None:
        raise HTTPException(422, "UTC offset required")
    post.scheduled_for_utc = payload.scheduled_for_utc.astimezone(UTC).replace(tzinfo=None)
    post.status = "SCHEDULED"
    post.writeback_pending = True
    session.commit()
    return _serialize(session, post)


@router.post("/posts/{post_id}/cancel")
def cancel(
    post_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_active_user)],
) -> dict:
    post = _post(session, user, post_id)
    if post.status not in {"READY", "SCHEDULED", "INVALID"}:
        raise HTTPException(409, "Post cannot be cancelled")
    post.status = "CANCELLED"
    post.writeback_pending = True
    session.commit()
    return _serialize(session, post)


@router.post("/posts/{post_id}/retry")
def retry(
    post_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_active_user)],
) -> dict:
    post = _post(session, user, post_id)
    if (
        post.status != "FAILED"
        or post.attempt_count >= 3
        or post.last_error_code
        not in {"GRAPH_REJECTED", "PAGE_UNAVAILABLE", "INVALID_IMAGE", "VERIFIED_ABSENT"}
    ):
        raise HTTPException(409, "Post is not safe to retry")
    post.status = "SCHEDULED"
    post.next_attempt_at = datetime.now(UTC)
    post.writeback_pending = True
    session.commit()
    return _serialize(session, post)


@router.post("/posts/{post_id}/resolve")
def resolve(
    post_id: UUID,
    payload: ResolutionInput,
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_admin)],
) -> dict:
    post = _post(session, user, post_id)
    if post.status != "UNCERTAIN" or not payload.confirmed:
        raise HTTPException(409, "Explicit verification is required")
    if payload.outcome == "published":
        if not payload.facebook_post_id:
            raise HTTPException(422, "Facebook post ID is required")
        post.status = "PUBLISHED"
        post.facebook_post_id = payload.facebook_post_id
        post.published_at = datetime.now(UTC)
    else:
        post.status = "FAILED"
        post.last_error_code = "VERIFIED_ABSENT"
        post.last_error_message = "Admin verified that Facebook did not publish this post"
    post.writeback_pending = True
    session.commit()
    return _serialize(session, post)
