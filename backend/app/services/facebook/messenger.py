"""Facebook Messenger webhook event processing service."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.models.facebook import FacebookPage
from app.models.messenger import Conversation, Message
from app.services.customer_identity import resolve_customer_for_conversation
from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import FacebookIntegrationError
from sqlalchemy.orm import Session


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
    mid: str | None       # Facebook message ID (None for read receipts without mid)
    event_type: str       # "message" | "postback" | "read"
    is_from_page: bool    # True if the Page sent the message (echo)
    text: str | None
    postback_payload: str | None
    fb_timestamp_ms: int | None


def parse_webhook_payload(payload: dict[str, Any]) -> list[RawMessageEvent]:
    """Extract all messaging events from a raw Facebook webhook payload dict.

    Facebook delivers one or more ``entry`` objects, each containing one or
    more ``messaging`` items.  We normalise them into a flat list of
    ``RawMessageEvent`` objects, skipping any entries we cannot parse.
    """
    events: list[RawMessageEvent] = []

    for entry in payload.get("entry", []):
        page_id = str(entry.get("id", ""))
        for item in entry.get("messaging", []):
            sender = item.get("sender", {})
            recipient = item.get("recipient", {})
            psid = str(sender.get("id", ""))
            page_sender_id = str(recipient.get("id", ""))
            fb_ts = item.get("timestamp")

            if not psid or not page_id:
                continue

            # ── plain message (including page echo) ──────────────────────────
            if "message" in item:
                msg = item["message"]
                # Skip delivery / read echo objects that have no mid
                mid = msg.get("mid")
                if not mid:
                    continue
                is_echo = bool(msg.get("is_echo", False))
                # When is_echo, the *sender* is the Page; psid is the customer
                if is_echo:
                    actual_psid = str(recipient.get("id", psid))
                    actual_page_id = str(sender.get("id", page_id))
                else:
                    actual_psid = psid
                    actual_page_id = page_sender_id or page_id
                events.append(
                    RawMessageEvent(
                        page_id=actual_page_id or page_id,
                        psid=actual_psid,
                        mid=mid,
                        event_type="message",
                        is_from_page=is_echo,
                        text=msg.get("text"),
                        postback_payload=None,
                        fb_timestamp_ms=int(fb_ts) if fb_ts is not None else None,
                    )
                )

            # ── postback ─────────────────────────────────────────────────────
            elif "postback" in item:
                postback = item["postback"]
                mid = postback.get("mid") or f"postback-{page_id}-{psid}-{fb_ts}"
                events.append(
                    RawMessageEvent(
                        page_id=page_sender_id or page_id,
                        psid=psid,
                        mid=mid,
                        event_type="postback",
                        is_from_page=False,
                        text=postback.get("title"),
                        postback_payload=postback.get("payload"),
                        fb_timestamp_ms=int(fb_ts) if fb_ts is not None else None,
                    )
                )

            # ── read receipt ─────────────────────────────────────────────────
            elif "read" in item:
                # Read receipts have no mid; we synthesise a stable key
                watermark = item["read"].get("watermark", fb_ts or 0)
                mid = f"read-{page_id}-{psid}-{watermark}"
                events.append(
                    RawMessageEvent(
                        page_id=page_sender_id or page_id,
                        psid=psid,
                        mid=mid,
                        event_type="read",
                        is_from_page=False,
                        text=None,
                        postback_payload=None,
                        fb_timestamp_ms=int(fb_ts) if fb_ts is not None else None,
                    )
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


def _fetch_customer_profile(facebook_page: FacebookPage, psid: str) -> tuple[str | None, str | None]:
    encrypted_token = facebook_page.access_token_encrypted
    if not encrypted_token and facebook_page.facebook_account is not None:
        encrypted_token = facebook_page.facebook_account.access_token_encrypted

    access_token = TokenCipher().decrypt(encrypted_token or "")
    client = FacebookGraphClient()
    response = client.get(
        f"{psid}",
        params={"fields": "name,picture.type(large)"},
        access_token=access_token,
    )

    customer_name = response.get("name")
    picture = response.get("picture", {})
    picture_data = picture.get("data", {}) if isinstance(picture, dict) else {}
    customer_avatar_url = picture_data.get("url") if isinstance(picture_data, dict) else None
    return (
        str(customer_name) if customer_name else None,
        str(customer_avatar_url) if customer_avatar_url else None,
    )


def hydrate_conversation_identity(session: Session, conversation: Conversation, facebook_page: FacebookPage) -> None:
    if conversation.customer_name and conversation.customer_avatar_url:
        return

    try:
        customer_name, customer_avatar_url = _fetch_customer_profile(facebook_page, conversation.psid)
    except FacebookIntegrationError:
        return

    updated = False
    if customer_name and not conversation.customer_name:
        conversation.customer_name = customer_name
        updated = True
    if customer_avatar_url and not conversation.customer_avatar_url:
        conversation.customer_avatar_url = customer_avatar_url
        updated = True
    if updated:
        session.add(conversation)
        session.flush()


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


def upsert_conversation(
    session: Session,
    facebook_page: FacebookPage,
    psid: str,
    event_ts: datetime | None,
) -> Conversation:
    """Return existing Conversation or create a new one (idempotent by page+psid)."""
    conversation = (
        session.query(Conversation)
        .filter(
            Conversation.facebook_page_id == facebook_page.id,
            Conversation.psid == psid,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )

    if conversation is None:
        conversation = Conversation(
            facebook_page_id=facebook_page.id,
            page_id=facebook_page.page_id,
            psid=psid,
        )
        session.add(conversation)
        session.flush()  # obtain PK before creating Message FK

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

    Events whose page_id does not correspond to a known FacebookPage are silently
    skipped — Facebook may deliver events for Pages that have since been
    disconnected.  Events with duplicate ``mid`` values are deduplicated by
    ``upsert_message`` (idempotent).
    """
    results: list[tuple[Conversation, Message, bool]] = []

    for event in events:
        page = find_page_by_page_id(session, event.page_id)
        if page is None:
            continue  # unknown / disconnected Page — skip silently

        event_ts = _ts_to_utc(event.fb_timestamp_ms)
        conversation = upsert_conversation(session, page, event.psid, event_ts)
        hydrate_conversation_identity(session, conversation, page)
        message, created = upsert_message(session, conversation, event)
        results.append((conversation, message, created))

    session.commit()
    for conversation, message, _ in results:
        session.refresh(conversation)
        session.refresh(message)

    return results
