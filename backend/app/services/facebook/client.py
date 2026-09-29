"""Small Graph API client with token-safe error handling."""

from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.services.facebook.exceptions import (
    FacebookApiError,
    FacebookPermissionError,
    FacebookRateLimitError,
    FacebookTokenError,
    FacebookTransportError,
)
from loguru import logger


class FacebookGraphClient:
    def __init__(self, api_version: str | None = None, timeout_seconds: float = 10.0) -> None:
        settings = get_settings()
        self.api_version = api_version or settings.facebook_api_version
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    def get(
        self, path: str, params: dict[str, Any] | None = None, access_token: str | None = None
    ) -> dict[str, Any]:
        query = dict(params or {})
        if access_token:
            query["access_token"] = access_token
        return self._request("GET", path, query)

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, data)

    def post_photo(
        self, path: str, access_token: str, caption: str, image: bytes, mime: str
    ) -> dict[str, Any]:
        """Upload a validated single photo as multipart source, avoiding a second URL fetch."""
        boundary = f"metacrm-{secrets.token_hex(16)}"
        parts = []
        for name, value in (("access_token", access_token), ("caption", caption)):
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode()
            )
        parts.append(
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="source"; filename="image"\r\n'
            f"Content-Type: {mime}\r\n\r\n".encode()
            + image
            + f"\r\n--{boundary}--\r\n".encode()
        )
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=b"".join(parts),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        return self._send(request)

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        clean_path = path.lstrip("/")
        url = f"{self.base_url}/{clean_path}"

        if method == "GET":
            request_url = f"{url}?{urlencode(payload)}" if payload else url
            request = Request(request_url, method="GET")
        else:
            body = urlencode(payload).encode("utf-8")
            request = Request(
                url,
                data=body,
                method=method,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        return self._send(request)

    def _send(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise self._api_error(body, exc.code) from exc
        except OSError as exc:
            logger.warning("Facebook Graph API network error")
            raise FacebookTransportError("Facebook API request outcome is unknown") from exc

        try:
            decoded = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise FacebookTransportError("Facebook API response outcome is unknown") from exc

        if isinstance(decoded, dict) and "error" in decoded:
            raise self._api_error(json.dumps(decoded), 200)
        if not isinstance(decoded, dict):
            raise FacebookTransportError("Facebook API response outcome is unknown")
        return decoded

    def _api_error(self, body: str, status_code: int) -> FacebookApiError:
        code: int | None = None

        try:
            decoded = json.loads(body)
            error = decoded.get("error", {})
            code = int(error["code"]) if "code" in error else None
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        logger.warning("Facebook Graph API error status={} code={}", status_code, code)
        if status_code >= 500:
            return FacebookTransportError("Facebook API response outcome is unknown")
        if status_code == 429 or code in {4, 17, 32, 613}:
            return FacebookRateLimitError("Facebook rate limit rejected the request")
        if code in {190, 463, 467}:
            return FacebookTokenError("Facebook token was rejected")
        if code in {10, 200, 299} or status_code in {401, 403}:
            return FacebookPermissionError("Facebook permission was denied")
        return FacebookApiError("Facebook API request failed")
