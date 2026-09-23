"""ASGI-level routing diagnostics."""

from __future__ import annotations

from loguru import logger
from starlette.types import ASGIApp, Receive, Scope, Send

FACEBOOK_WEBHOOK_PATH = "/api/v1/facebook/webhook"


class ASGIIngressLoggingMiddleware:
    """Log Facebook webhook traffic before FastAPI performs route dispatch."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == FACEBOOK_WEBHOOK_PATH:
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            client = scope.get("client")
            client_ip = str(client[0]) if client else "unknown"
            logger.info(
                "asgi_request_received_before_dispatch method={} path={} root_path={} "
                "client_ip={} request_id={} content_length={} signature_present={}",
                scope.get("method", "UNKNOWN"),
                scope.get("path", ""),
                scope.get("root_path", ""),
                client_ip,
                headers.get("x-request-id", "unknown"),
                headers.get("content-length", "unknown"),
                "x-hub-signature-256" in headers,
            )
        await self.app(scope, receive, send)
