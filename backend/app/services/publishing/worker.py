"""Single-attempt DB-backed Page publisher. Run as a dedicated process."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from app.models.facebook import FacebookAccount, FacebookPage
from app.models.publishing import ScheduledPost
from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import (
    FacebookApiError,
    FacebookConfigurationError,
    FacebookPermissionError,
    FacebookRateLimitError,
    FacebookTokenError,
    FacebookTransportError,
)
from app.services.publishing.media import MediaError, inspect_image
from app.services.publishing.sheet import SheetError
from app.services.publishing.sync import flush_writebacks
from sqlalchemy import select
from sqlalchemy.orm import Session

MAX_ATTEMPTS = 3
CLAIM_AGE = timedelta(minutes=5)


def claim_due(session: Session, now: datetime | None = None) -> int | None:
    now = (now or datetime.now(UTC)).replace(tzinfo=None)
    post = session.scalar(
        select(ScheduledPost)
        .where(
            ScheduledPost.status == "SCHEDULED",
            ScheduledPost.scheduled_for_utc <= now,
            (ScheduledPost.next_attempt_at.is_(None) | (ScheduledPost.next_attempt_at <= now)),
        )
        .order_by(ScheduledPost.scheduled_for_utc, ScheduledPost.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if post is None:
        session.rollback()
        return None
    post.status = "PUBLISHING"
    post.claimed_at = now
    post.publish_started_at = now
    post.attempt_count += 1
    post.request_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "page": post.facebook_page_id,
                "caption": post.caption,
                "image": post.image_url,
                "schedule": str(post.scheduled_for_utc),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    post.writeback_pending = True
    post_id = post.id
    session.commit()
    return post_id


def mark_stale_uncertain(session: Session, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)).replace(tzinfo=None) - CLAIM_AGE
    posts = session.scalars(
        select(ScheduledPost)
        .where(
            ScheduledPost.status == "PUBLISHING",
            ScheduledPost.claimed_at < cutoff,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for post in posts:
        post.status = "UNCERTAIN"
        post.last_error_code = "STALE_CLAIM"
        post.last_error_message = "Worker stopped during publishing; verify on Facebook"
        post.writeback_pending = True
    session.commit()
    return len(posts)


def publish_claimed(
    session: Session, post_id: int, graph: FacebookGraphClient | None = None
) -> str:
    post = session.get(ScheduledPost, post_id)
    if post is None or post.status != "PUBLISHING":
        return "SKIPPED"
    page = session.get(FacebookPage, post.facebook_page_id)
    account = session.get(FacebookAccount, page.facebook_account_id) if page else None
    image_url, caption = post.image_url, post.caption
    page_id = page.page_id if page else None
    encrypted_token = page.access_token_encrypted if page else None
    attempt_count = post.attempt_count
    page_available = bool(
        page
        and page.is_active
        and page.deleted_at is None
        and encrypted_token
        and account
        and account.is_active
        and account.deleted_at is None
    )
    session.rollback()  # Release the read transaction before external network I/O.
    if not page_available:
        outcome, code, detail = "FAILED", "PAGE_UNAVAILABLE", "Page is disconnected"
        provider_id = None
    else:
        try:
            if image_url:
                image, mime = inspect_image(image_url)
            token = TokenCipher().decrypt(encrypted_token)
            if image_url:
                endpoint = f"/{page_id}/photos"
                response = (graph or FacebookGraphClient()).post_photo(
                    endpoint, token, caption, image, mime
                )
            else:
                endpoint = f"/{page_id}/feed"
                response = (graph or FacebookGraphClient()).post(
                    endpoint, {"access_token": token, "message": caption}
                )
            provider_id = str((response.get("post_id") if image_url else response.get("id")) or "")
            if not provider_id:
                raise FacebookTransportError("Facebook response omitted post ID")
            outcome, code, detail = "PUBLISHED", None, None
        except MediaError:
            outcome, code, detail, provider_id = (
                "FAILED",
                "INVALID_IMAGE",
                "Image URL is invalid or unavailable",
                None,
            )
        except FacebookTransportError:
            outcome, code, detail, provider_id = (
                "UNCERTAIN",
                "TRANSPORT",
                "Facebook request outcome is unknown",
                None,
            )
        except FacebookRateLimitError:
            if attempt_count < MAX_ATTEMPTS:
                outcome, code, detail, provider_id = (
                    "SCHEDULED",
                    "RATE_LIMIT",
                    "Facebook rate limit; retry scheduled",
                    None,
                )
            else:
                outcome, code, detail, provider_id = (
                    "FAILED",
                    "RATE_LIMIT",
                    "Facebook rate limit retry limit reached",
                    None,
                )
        except FacebookTokenError:
            outcome, code, detail, provider_id = (
                "FAILED",
                "INVALID_TOKEN",
                "Reconnect the Facebook Page",
                None,
            )
        except FacebookPermissionError:
            outcome, code, detail, provider_id = (
                "FAILED",
                "MISSING_PERMISSION",
                "Reconnect the Page and grant publishing access",
                None,
            )
        except FacebookApiError:
            outcome, code, detail, provider_id = (
                "FAILED",
                "GRAPH_REJECTED",
                "Facebook rejected the request",
                None,
            )
        except FacebookConfigurationError:
            outcome, code, detail, provider_id = (
                "FAILED",
                "CONFIGURATION",
                "Facebook token configuration is unavailable",
                None,
            )
    # A stale-claim recovery process may have marked this UNCERTAIN. Never override it.
    locked = session.scalar(
        select(ScheduledPost)
        .where(ScheduledPost.id == post_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.status != "PUBLISHING":
        session.rollback()
        return "UNCERTAIN"
    locked.status = outcome
    locked.facebook_post_id = provider_id
    locked.last_error_code = code
    locked.last_error_message = detail
    locked.published_at = datetime.now(UTC).replace(tzinfo=None) if outcome == "PUBLISHED" else None
    locked.next_attempt_at = (
        datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=30 * 2 ** (attempt_count - 1))
        if outcome == "SCHEDULED"
        else None
    )
    locked.writeback_pending = True
    session.commit()
    return outcome


def run_once(session: Session, graph: FacebookGraphClient | None = None) -> str:
    mark_stale_uncertain(session)
    post_id = claim_due(session)
    if post_id is None:
        try:
            flush_writebacks(session)
        except SheetError:
            session.rollback()
            pass  # Imported schedules remain executable while Sheets is offline.
        return "IDLE"
    try:
        flush_writebacks(session, only_post_id=post_id)  # Best-effort PUBLISHING status.
    except SheetError:
        session.rollback()
        pass
    outcome = publish_claimed(session, post_id, graph)
    try:
        flush_writebacks(session)
    except SheetError:
        session.rollback()
        pass
    return outcome
