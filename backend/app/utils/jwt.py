"""JWT creation and validation utilities."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from app.core.config import get_settings
from jwt.exceptions import InvalidTokenError


def _create_token(
    subject: str,
    expires_delta: timedelta,
    token_type: str,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed token with an explicit intended use."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + expires_delta,
        "type": token_type,
    }
    if additional_claims:
        payload.update(additional_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, additional_claims: dict[str, Any] | None = None) -> str:
    """Create a signed, expiring access token for a subject."""
    settings = get_settings()
    return _create_token(
        subject,
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
        additional_claims,
    )


def create_refresh_token(subject: str) -> str:
    """Create a signed refresh token for a subject."""
    settings = get_settings()
    return _create_token(subject, timedelta(days=settings.refresh_token_expire_days), "refresh")


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate and decode an access token; raises InvalidTokenError if invalid."""
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


__all__ = [
    "InvalidTokenError",
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
]
