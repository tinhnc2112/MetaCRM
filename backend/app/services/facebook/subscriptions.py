"""Messenger webhook subscription lifecycle for Facebook Pages."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from app.models.facebook import FacebookPage
from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import (
    FacebookApiError,
    FacebookPermissionError,
    FacebookTokenError,
)
from loguru import logger
from sqlalchemy.orm import Session

SUBSCRIPTION_PENDING = "pending"
SUBSCRIPTION_SUBSCRIBED = "subscribed"
SUBSCRIPTION_FAILED = "failed"
SUBSCRIBED_FIELDS = (
    "messages,messaging_postbacks,messaging_optins,message_deliveries,"
    "message_reads,messaging_referrals"
)
MAX_ATTEMPTS = 3
PENDING_LEASE = timedelta(seconds=30)
RETRY_DELAYS_SECONDS = (0.25, 0.5)


def subscribe_active_pages_to_messenger_webhooks(
    session: Session,
    pages: Iterable[FacebookPage],
    *,
    client: FacebookGraphClient | None = None,
    cipher: TokenCipher | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Subscribe every active Page while isolating per-Page failures."""
    active_pages = [
        page for page in pages if page.is_active and page.deleted_at is None
    ]
    logger.info(
        "facebook_webhook_subscription_batch_started page_count={}",
        len(active_pages),
    )

    subscribed_count = 0
    skipped_count = 0
    pending_count = 0
    failed_count = 0
    for page in active_pages:
        was_subscribed = page.webhook_subscription_status == SUBSCRIPTION_SUBSCRIBED
        subscribed = subscribe_page_to_messenger_webhooks(
            session,
            page,
            client=client,
            cipher=cipher,
            sleep=sleep,
        )
        if was_subscribed:
            skipped_count += 1
        elif subscribed:
            subscribed_count += 1
        elif page.webhook_subscription_status == SUBSCRIPTION_PENDING:
            pending_count += 1
        else:
            failed_count += 1

    logger.info(
        "facebook_webhook_subscription_batch_completed page_count={} subscribed_count={} skipped_count={} pending_count={} failed_count={}",
        len(active_pages),
        subscribed_count,
        skipped_count,
        pending_count,
        failed_count,
    )


def subscribe_page_to_messenger_webhooks(
    session: Session,
    page: FacebookPage,
    *,
    client: FacebookGraphClient | None = None,
    cipher: TokenCipher | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Subscribe a Page, returning whether it is confirmed subscribed."""
    now = datetime.now(UTC)
    if page.webhook_subscription_status == SUBSCRIPTION_SUBSCRIBED:
        logger.info(
            "facebook_webhook_subscription_skipped page_id={} reason=already_subscribed",
            page.page_id,
        )
        return True

    if (
        page.webhook_subscription_status == SUBSCRIPTION_PENDING
        and page.webhook_subscription_last_attempt_at is not None
        and _as_utc(page.webhook_subscription_last_attempt_at) >= now - PENDING_LEASE
    ):
        logger.info(
            "facebook_webhook_subscription_skipped page_id={} reason=attempt_in_progress",
            page.page_id,
        )
        return False

    if not page.access_token_encrypted:
        _mark_failed(session, page, "Page Access Token is unavailable")
        logger.warning(
            "facebook_webhook_subscription_failed page_id={} reason=missing_page_token",
            page.page_id,
        )
        return False

    try:
        token_cipher = cipher or TokenCipher()
        page_access_token = token_cipher.decrypt(page.access_token_encrypted)
    except Exception as exc:
        _mark_failed(session, page, "Page Access Token could not be decrypted")
        logger.warning(
            "facebook_webhook_subscription_failed page_id={} reason=token_decryption error_type={}",
            page.page_id,
            type(exc).__name__,
        )
        return False

    graph = client or FacebookGraphClient()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        page.webhook_subscription_status = SUBSCRIPTION_PENDING
        page.webhook_subscription_attempt_count += 1
        page.webhook_subscription_last_attempt_at = datetime.now(UTC)
        page.webhook_subscription_last_error = None
        session.commit()

        logger.info(
            "facebook_webhook_subscription_attempt page_id={} attempt={} max_attempts={}",
            page.page_id,
            attempt,
            MAX_ATTEMPTS,
        )
        try:
            response = graph.post(
                f"/{page.page_id}/subscribed_apps",
                {
                    "subscribed_fields": SUBSCRIBED_FIELDS,
                    "access_token": page_access_token,
                },
            )
            if response.get("success") is not True:
                raise FacebookApiError("Facebook API did not confirm the Page subscription")
        except (FacebookPermissionError, FacebookTokenError) as exc:
            _mark_failed(session, page, str(exc))
            logger.warning(
                "facebook_webhook_subscription_failed page_id={} attempt={} retryable=false error_type={}",
                page.page_id,
                attempt,
                type(exc).__name__,
            )
            return False
        except FacebookApiError as exc:
            if attempt < MAX_ATTEMPTS:
                delay = RETRY_DELAYS_SECONDS[attempt - 1]
                logger.warning(
                    "facebook_webhook_subscription_retry page_id={} attempt={} next_attempt={} delay_seconds={} error_type={}",
                    page.page_id,
                    attempt,
                    attempt + 1,
                    delay,
                    type(exc).__name__,
                )
                sleep(delay)
                continue

            _mark_failed(session, page, str(exc))
            logger.warning(
                "facebook_webhook_subscription_failed page_id={} attempt={} retryable=true error_type={}",
                page.page_id,
                attempt,
                type(exc).__name__,
            )
            return False

        subscribed_at = datetime.now(UTC)
        page.webhook_subscription_status = SUBSCRIPTION_SUBSCRIBED
        page.webhook_subscribed_at = subscribed_at
        page.webhook_subscription_last_attempt_at = subscribed_at
        page.webhook_subscription_last_error = None
        session.commit()
        session.refresh(page)
        logger.info(
            "facebook_webhook_subscription_succeeded page_id={} attempt={}",
            page.page_id,
            attempt,
        )
        return True

    return False


def _mark_failed(session: Session, page: FacebookPage, error: str) -> None:
    page.webhook_subscription_status = SUBSCRIPTION_FAILED
    page.webhook_subscription_last_attempt_at = datetime.now(UTC)
    page.webhook_subscription_last_error = error[:1000]
    session.commit()
    session.refresh(page)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
