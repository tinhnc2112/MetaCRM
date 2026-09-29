"""Import Sheet snapshots into durable schedules and flush status independently."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.models.facebook import FacebookAccount, FacebookPage
from app.models.publishing import ScheduledPost, SheetPublishingConfig, source_identity_key
from app.services.publishing.parser import parse_rows
from app.services.publishing.sheet import SheetError, SheetsClient
from sqlalchemy import select
from sqlalchemy.orm import Session

STATUS_TEXT = {
    "INVALID": "Lỗi",
    "READY": "Chưa đăng",
    "SCHEDULED": "Đã lên lịch",
    "PUBLISHING": "Đang đăng",
    "PUBLISHED": "Đã đăng",
    "FAILED": "Lỗi",
    "UNCERTAIN": "Không chắc chắn",
    "CANCELLED": "Đã hủy",
}


def get_config(session: Session) -> SheetPublishingConfig | None:
    return session.get(SheetPublishingConfig, 1)


def sync_sheet(session: Session, client: SheetsClient | None = None) -> dict[str, int]:
    config = get_config(session)
    if config is None:
        raise ValueError("Sheet publishing is not configured")
    source = (config.spreadsheet_id, config.worksheet, config.timezone)
    sheet = client or SheetsClient()
    rows, errors = parse_rows(sheet.read(source[0], source[1]), source[2])
    session.rollback()  # Do not retain a DB transaction across the Sheet request.
    config = session.scalar(
        select(SheetPublishingConfig).where(SheetPublishingConfig.id == 1).with_for_update()
    )
    if config is None or (config.spreadsheet_id, config.worksheet, config.timezone) != source:
        raise ValueError("Sheet configuration changed during sync; retry")
    pages = session.scalars(
        select(FacebookPage).join(FacebookAccount).where(
            FacebookPage.is_active.is_(True), FacebookPage.deleted_at.is_(None),
            FacebookAccount.is_active.is_(True), FacebookAccount.deleted_at.is_(None),
        )
    ).all()
    created = updated = unchanged = invalid = 0
    for row in rows:
        key = source_identity_key(
            "google_sheet", config.spreadsheet_id, config.worksheet, row.external_id
        )
        scheduled_utc = row.scheduled_for_utc.replace(tzinfo=None)
        matches = [page for page in pages if row.page in {page.page_id, page.name, page.username}]
        error = (
            None if len(matches) == 1 else ("Page not found" if not matches else "Ambiguous Page")
        )
        post = session.scalar(
            select(ScheduledPost)
            .where(
                ScheduledPost.source_key == key,
            )
            .with_for_update()
        )
        if post is not None and post.status in {
            "PUBLISHING",
            "PUBLISHED",
            "UNCERTAIN",
            "CANCELLED",
            "FAILED",
        }:
            unchanged += 1
            continue
        if post is None:
            post = ScheduledPost(
                source="google_sheet",
                source_key=key,
                spreadsheet_id=config.spreadsheet_id,
                worksheet=config.worksheet,
                external_id=row.external_id,
                source_timezone=config.timezone,
                status="INVALID",
            )
            session.add(post)
            created += 1
        elif (
            post.caption,
            post.image_url,
            post.scheduled_for_utc,
            post.facebook_page_id,
            post.status,
        ) == (
            row.caption,
            row.image_url,
            scheduled_utc,
            matches[0].id if not error else None,
            "INVALID" if error else "SCHEDULED",
        ):
            unchanged += 1
            continue
        else:
            updated += 1
        retain_backoff = post.last_error_code == "RATE_LIMIT"
        post.source_row = row.row_number
        post.facebook_page_id = matches[0].id if not error else None
        post.caption = row.caption
        post.image_url = row.image_url
        post.scheduled_for_utc = scheduled_utc
        post.source_timezone = config.timezone
        post.status = "INVALID" if error else "SCHEDULED"
        post.last_error_code = "PAGE" if error else None
        post.last_error_message = error
        if not retain_backoff:
            post.next_attempt_at = None
        post.writeback_pending = True
        if error:
            invalid += 1
    session.flush()  # Duplicate-ID errors must see new rows from this same sync.
    for row_number, external_id, error in errors:
        if not external_id or len(external_id) > 255:
            invalid += 1
            continue
        key = source_identity_key(
            "google_sheet", config.spreadsheet_id, config.worksheet, external_id
        )
        post = session.scalar(
            select(ScheduledPost)
            .where(
                ScheduledPost.source_key == key,
            )
            .with_for_update()
        )
        if post is not None and post.status in {
            "PUBLISHING",
            "PUBLISHED",
            "UNCERTAIN",
            "CANCELLED",
            "FAILED",
        }:
            continue
        if post is None:
            post = ScheduledPost(
                source="google_sheet",
                source_key=key,
                spreadsheet_id=config.spreadsheet_id,
                worksheet=config.worksheet,
                external_id=external_id,
                source_timezone=config.timezone,
                status="INVALID",
                caption="",
            )
            session.add(post)
            created += 1
        post.status = "INVALID"
        post.source_row = row_number
        post.last_error_code = "SHEET_ROW"
        post.last_error_message = error[:500]
        post.writeback_pending = True
        invalid += 1
    result = {"created": created, "updated": updated, "unchanged": unchanged, "invalid": invalid}
    config.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
    config.last_sync_error = None
    config.last_sync_result = json.dumps(result)
    session.commit()
    flush_writebacks(session, sheet)
    return result


def flush_writebacks(
    session: Session,
    client: SheetsClient | None = None,
    limit: int = 100,
    only_post_id: int | None = None,
) -> int:
    query = select(ScheduledPost).where(ScheduledPost.writeback_pending.is_(True))
    if only_post_id is not None:
        query = query.where(ScheduledPost.id == only_post_id)
    posts = session.scalars(query.order_by(ScheduledPost.id).limit(limit)).all()
    if not posts:
        return 0
    sheet = client or SheetsClient()
    written = 0
    snapshots: dict[tuple[str, str], list[list[str]]] = {}
    for post in posts:
        if post.source_row is None:
            continue
        try:
            source = (post.spreadsheet_id, post.worksheet)
            if source not in snapshots:
                snapshots[source] = sheet.read(*source)
            values = snapshots[source]
            if (
                len(values) < post.source_row
                or not values[post.source_row - 1]
                or str(values[post.source_row - 1][0]).strip() != post.external_id
            ):
                post.writeback_error = "Source row moved or ID changed; sync to relocate"
                continue
            sheet.write_status(
                post.spreadsheet_id, post.worksheet, post.source_row, STATUS_TEXT[post.status]
            )
            post.writeback_pending = False
            post.writeback_error = None
            written += 1
        except (SheetError, OSError):
            post.writeback_error = "Google Sheets status write failed"
    session.commit()
    return written
