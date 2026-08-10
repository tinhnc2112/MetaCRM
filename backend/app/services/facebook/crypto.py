"""Token encryption helpers for Facebook access tokens."""

from __future__ import annotations

import base64
import hashlib

from app.core.config import get_settings
from cryptography.fernet import Fernet, InvalidToken

from app.services.facebook.exceptions import FacebookConfigurationError, FacebookTokenError


def _normalize_key(secret: str) -> bytes:
    if not secret:
        raise FacebookConfigurationError("FACEBOOK_TOKEN_ENCRYPTION_KEY is not configured")

    encoded = secret.encode("utf-8")
    try:
        Fernet(encoded)
        return encoded
    except ValueError:
        digest = hashlib.sha256(encoded).digest()
        return base64.urlsafe_b64encode(digest)


class TokenCipher:
    """Encrypt and decrypt access tokens with an environment-backed Fernet key."""

    def __init__(self, secret: str | None = None) -> None:
        settings = get_settings()
        self._fernet = Fernet(_normalize_key(secret or settings.facebook_token_encryption_key))

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise FacebookTokenError("Stored Facebook token could not be decrypted") from exc
