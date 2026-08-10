"""Small Graph API client with token-safe error handling."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import get_settings
from loguru import logger

from app.services.facebook.exceptions import FacebookApiError, FacebookPermissionError, FacebookTokenError


class FacebookGraphClient:
    def __init__(self, api_version: str | None = None, timeout_seconds: float = 10.0) -> None:
        settings = get_settings()
        self.api_version = api_version or settings.facebook_api_version
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    def get(self, path: str, params: dict[str, Any] | None = None, access_token: str | None = None) -> dict[str, Any]:
        query = dict(params or {})
        if access_token:
            query["access_token"] = access_token
        return self._request("GET", path, query)

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, data)

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

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise self._api_error(body, exc.code) from exc
        except URLError as exc:
            logger.warning("Facebook Graph API network error for {}", clean_path)
            raise FacebookApiError("Facebook API request failed") from exc

        try:
            decoded = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise FacebookApiError("Facebook API returned invalid JSON") from exc

        if isinstance(decoded, dict) and "error" in decoded:
            raise self._api_error(json.dumps(decoded), 200)
        if not isinstance(decoded, dict):
            raise FacebookApiError("Facebook API returned an unexpected response")
        return decoded

    def _api_error(self, body: str, status_code: int) -> FacebookApiError:
        message = "Facebook API request failed"
        code: int | None = None

        try:
            decoded = json.loads(body)
            error = decoded.get("error", {})
            message = str(error.get("message") or message)
            code = int(error["code"]) if "code" in error else None
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        logger.warning("Facebook Graph API error status={} code={}", status_code, code)
        if code in {190, 463, 467}:
            return FacebookTokenError(message)
        if code in {10, 200, 299} or status_code in {401, 403}:
            return FacebookPermissionError(message)
        return FacebookApiError(message)
