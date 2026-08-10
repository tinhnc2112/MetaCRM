"""Pydantic schemas for Messenger webhook responses."""

from __future__ import annotations

from pydantic import BaseModel


class WebhookAcceptedResponse(BaseModel):
    """Returned after successfully processing a webhook POST."""

    received: bool = True
    events_processed: int
