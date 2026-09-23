"""Facebook Messenger webhook event processing service."""

from __future__ import annotations

import hashlib
import logging
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.models.facebook import FacebookPage
from app.models.messenger import Conversation, Message
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.exceptions import FacebookIntegrationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


class FacebookWebhookSignatureError(FacebookIntegrationError):
    """Raised when the X-Hub-Signature-256 header is missing or does not match."""


def verify_webhook_signature(body: bytes, signature_header: str | None, app_secret: str) -> None:
    """Raise `FacebookWebhookSignatureError` if the payload signature is invalid.

    Facebook sends ``sha256=<hex>`` in the ``X-Hub-Signature-256`` header.
    We compute HMAC-SHA256 of the raw request body with the App Secret and
    compare using a constant-time comparison to prevent timing attacks.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        raise FacebookWebhookSignatureError("Missing or malformed X-Hub-Signature-256 header")

    received_hex = signature_header[len("sha256="):]
    expected_hex = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(received_hex, expected_hex):
        raise FacebookWebhookSignatureError("X-Hub-Signature-256 does not match payload")


# ---------------------------------------------------------------------------
# Payload parsing dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawMessageEvent:
    """Parsed representation of a single messaging entry from Facebook."""

    page_id: str          # the recipient Page ID (sender in page-scoped events)
    psid: str             # Page-scoped user ID of the end-user
    mid: str | None       # Facebook message ID (None for non-message events without mid)
    event_type: str       # "message" | "postback"
    is_from_page: bool    # True if the Page sent the message (echo)
    text: str | None
    postback_payload: str | None
    fb_timestamp_ms: int | None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_webhook_payload(payload: dict[str, Any]) -> list[RawMessageEvent]:
    """Extract all messaging events from a raw Facebook webhook payload dict.

    Facebook delivers one or more ``entry`` objects, each containing one or
    more ``messaging`` items.  We normalise them into a flat list of
    ``RawMessageEvent`` objects, skipping unsupported delivery/read events
    while logging why they were ignored.
    """
    events: list[RawMessageEvent] = []

    for entry in _as_list(payload.get("entry")):
        if not isinstance(entry, dict):
            logger.info("facebook webhook ignored event_type=entry reason=non_object_entry")
            continue

        entry_id = str(entry.get("id") or "")
        messaging_items = _as_list(entry.get("messaging"))
        logger.info(
            "facebook webhook entry parsed entry_id=%s page_id=%s messaging_count=%d",
            entry_id or "",
            entry_id or "",
            len(messaging_items),
        )

        for item in messaging_items:
            if not isinstance(item, dict):
                logger.info(
                    "facebook webhook ignored event_type=messaging reason=non_object_item entry_id=%s",
                    entry_id or "",
                )
                continue

            sender = _as_dict(item.get("sender"))
            recipient = _as_dict(item.get("recipient"))
            psid = str(sender.get("id", ""))
            recipient_id = str(recipient.get("id", ""))
            fb_ts = _coerce_int(item.get("timestamp"))

            if not psid or not entry_id:
                logger.info(
                    "facebook webhook ignored event_type=messaging reason=missing_sender_or_entry entry_id=%s recipient_id=%s",
                    entry_id or "",
                    recipient_id or "",
                )
                continue

            # ── plain message (including page echo) ──────────────────────────
            if "message" in item:
                msg = item["message"]
                if not isinstance(msg, dict):
                    logger.info(
                        "facebook webhook ignored event_type=message reason=non_object_message entry_id=%s recipient_id=%s",
                        entry_id or "",
                        recipient_id or "",
                    )
                    continue

                mid = msg.get("mid")
                text = msg.get("text")
                is_echo = bool(msg.get("is_echo", False))
                logger.info(
                    "facebook webhook messaging item event_type=message entry_id=%s page_id=%s recipient_id=%s sender_id=%s mid=%s message_text_present=%s is_echo=%s",
                    entry_id or "",
                    entry_id or "",
                    recipient_id or "",
                    psid,
                    mid or "",
                    text is not None,
                    is_echo,
                )
                if not mid:
                    logger.info(
                        "facebook webhook ignored event_type=message reason=missing_mid entry_id=%s recipient_id=%s sender_id=%s",
                        entry_id or "",
                        recipient_id or "",
                        psid,
                    )
                    continue
                # When is_echo, the *sender* is the Page; psid is the customer
                if is_echo:
                    actual_psid = str(recipient.get("id", psid))
                    actual_page_id = str(sender.get("id", entry_id))
                else:
                    actual_psid = psid
                    actual_page_id = recipient_id or entry_id
                events.append(
                    RawMessageEvent(
                        page_id=actual_page_id or entry_id,
                        psid=actual_psid,
                        mid=mid,
                        event_type="message",
                        is_from_page=is_echo,
                        text=text if isinstance(text, str) or text is None else str(text),
                        postback_payload=None,
                        fb_timestamp_ms=fb_ts,
                    )
                )

            # ── postback ─────────────────────────────────────────────────────
            elif "postback" in item:
                postback = item["postback"]
                if not isinstance(postback, dict):
                    logger.info(
                        "facebook webhook ignored event_type=postback reason=non_object_postback entry_id=%s recipient_id=%s",
                        entry_id or "",
                        recipient_id or "",
                    )
                    continue
                mid = postback.get("mid") or f"postback-{entry_id}-{psid}-{fb_ts}"
                postback_title = postback.get("title")
                postback_payload = postback.get("payload")
                logger.info(
                    "facebook webhook messaging item event_type=postback entry_id=%s page_id=%s recipient_id=%s sender_id=%s mid=%s text_present=%s",
                    entry_id or "",
                    entry_id or "",
                    recipient_id or "",
                    psid,
                    mid,
                    postback_title is not None,
                )
                events.append(
                    RawMessageEvent(
                        page_id=recipient_id or entry_id,
                        psid=psid,
                        mid=mid,
                        event_type="postback",
                        is_from_page=False,
                        text=postback_title if isinstance(postback_title, str) or postback_title is None else str(postback_title),
                        postback_payload=postback_payload if isinstance(postback_payload, str) or postback_payload is None else str(postback_payload),
                        fb_timestamp_ms=fb_ts,
                    )
                )

            # ── read receipt ─────────────────────────────────────────────────
            elif "read" in item:
                logger.info(
                    "facebook webhook ignored event_type=read reason=unsupported entry_id=%s recipient_id=%s sender_id=%s",
                    entry_id or "",
                    recipient_id or "",
                    psid,
                )
                continue

            elif "delivery" in item:
                logger.info(
                    "facebook webhook ignored event_type=delivery reason=unsupported entry_id=%s recipient_id=%s sender_id=%s",
                    entry_id or "",
                    recipient_id or "",
                    psid,
                )
                continue

            else:
                logger.info(
                    "facebook webhook ignored event_type=unknown reason=unsupported_payload entry_id=%s recipient_id=%s sender_id=%s keys=%s",
                    entry_id or "",
                    recipient_id or "",
                    psid,
                    sorted(item.keys()),
                )

    return events


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _ts_to_utc(fb_timestamp_ms: int | None) -> datetime | None:
    if fb_timestamp_ms is None:
        return None
    return datetime.fromtimestamp(fb_timestamp_ms / 1000.0, tz=UTC)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalise a datetime to UTC-aware, handling both naive and aware values.

    SQLite (used in tests) does not store timezone information, so values read
    back from the DB may be timezone-naive even when the column is declared
    ``DateTime(timezone=True)``.  We treat any naive datetime as implicitly UTC
    so that comparisons with aware datetimes never raise ``TypeError``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Naive — assume UTC (matches column declaration intent)
        return dt.replace(tzinfo=UTC)
    # Already aware — convert to UTC in case it carries a different zone
    return dt.astimezone(UTC)


def find_page_by_page_id(session: Session, page_id: str) -> FacebookPage | None:
    """Return the active FacebookPage record for the given page_id string."""
    return (
        session.query(FacebookPage)
        .filter(
            FacebookPage.page_id == page_id,
            FacebookPage.deleted_at.is_(None),
        )
        .first()
    )


def _find_conversation(session: Session, facebook_page_id: int, psid: str) -> Conversation | None:
    return (
        session.query(Conversation)
        .filter(
            Conversation.facebook_page_id == facebook_page_id,
            Conversation.psid == psid,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )


def upsert_conversation(
    session: Session,
    facebook_page: FacebookPage,
    psid: str,
    event_ts: datetime | None,
) -> Conversation:
    """Return existing Conversation or create a new one (idempotent by page+psid)."""
    conversation = _find_conversation(session, facebook_page.id, psid)

    if conversation is None:
        try:
            with session.begin_nested():
                conversation = Conversation(
                    facebook_page_id=facebook_page.id,
                    page_id=facebook_page.page_id,
                    psid=psid,
                )
                session.add(conversation)
                session.flush()  # unique Page+PSID constraint arbitrates races
        except IntegrityError:
            conversation = _find_conversation(session, facebook_page.id, psid)
            if conversation is None:
                raise

    # M19.6: every Conversation must be linked to a channel-independent
    # Customer — both a brand-new Conversation created above AND a
    # pre-existing legacy row (created before M19.6) whose customer_id is
    # still NULL. resolve_customer_for_conversation() is idempotent: it
    # returns immediately with no extra query/write when customer_id is
    # already set, so calling it unconditionally here is a no-op for the
    # common case (existing conversation already linked, e.g. after a
    # Customer merge re-pointed it to the primary customer) and only does
    # real work for the new/legacy-NULL cases.
    resolve_customer_for_conversation(session, conversation)

    # Update last_message_at if this event is more recent.
    # Normalise both sides to UTC-aware before comparing to avoid TypeError
    # when SQLite returns timezone-naive datetimes from DateTime(timezone=True)
    # columns.
    if event_ts is not None:
        event_ts_utc = _ensure_utc(event_ts)
        last_at_utc = _ensure_utc(conversation.last_message_at)
        if last_at_utc is None or event_ts_utc > last_at_utc:
            conversation.last_message_at = event_ts_utc

    return conversation


def upsert_message(
    session: Session,
    conversation: Conversation,
    event: RawMessageEvent,
) -> tuple[Message, bool]:
    """Return (message, created) — idempotent by ``mid``."""
    existing = (
        session.query(Message)
        .filter(Message.mid == event.mid)
        .first()
    )
    if existing is not None:
        logger.info(
            "facebook webhook ignored event_type=%s reason=duplicate_mid page_id=%s psid=%s mid=%s",
            event.event_type,
            conversation.page_id,
            conversation.psid,
            event.mid,
        )
        return existing, False

    sent_at = _ts_to_utc(event.fb_timestamp_ms)
    message = Message(
        conversation_id=conversation.id,
        mid=event.mid,
        event_type=event.event_type,
        is_from_page=event.is_from_page,
        text=event.text,
        postback_payload=event.postback_payload,
        fb_timestamp_ms=event.fb_timestamp_ms,
        sent_at=sent_at,
    )
    session.add(message)
    return message, True


def process_webhook_events(
    session: Session,
    events: list[RawMessageEvent],
) -> list[tuple[Conversation, Message, bool]]:
    """Persist all events; return list of (conversation, message, was_created).

    Events whose page_id does not correspond to a known FacebookPage are
    logged and skipped — Facebook may deliver events for Pages that have since
    been disconnected.  Events with duplicate ``mid`` values are deduplicated
    by ``upsert_message`` (idempotent).
    """
    results: list[tuple[Conversation, Message, bool]] = []

    for event in events:
        page = find_page_by_page_id(session, event.page_id)
        if page is None:
            logger.info(
                "facebook webhook ignored event_type=%s reason=unknown_page page_id=%s psid=%s mid=%s",
                event.event_type,
                event.page_id,
                event.psid,
                event.mid,
            )
            continue  # unknown / disconnected Page — skip silently

        event_ts = _ts_to_utc(event.fb_timestamp_ms)
        conversation = upsert_conversation(session, page, event.psid, event_ts)
        message, created = upsert_message(session, conversation, event)
        results.append((conversation, message, created))

    session.commit()
    for conversation, message, _ in results:
        session.refresh(conversation)
        session.refresh(message)

    return results
