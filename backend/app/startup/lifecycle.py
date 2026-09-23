"""FastAPI lifespan hooks."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.init_db import init_db
from app.db.session import dispose_engine
from app.middleware.routing import FACEBOOK_WEBHOOK_PATH
from app.websocket.manager import ConnectionManager


def log_registered_routes(app: FastAPI) -> None:
    """Log the complete route table and explicitly verify the webhook POST route."""
    registered_routes: list[tuple[str, str, str]] = []
    webhook_post_registered = False

    for route in app.routes:
        path = str(getattr(route, "path", "UNKNOWN"))
        route_name = str(getattr(route, "name", "UNKNOWN"))
        methods = getattr(route, "methods", None)
        method_names = sorted(str(method) for method in methods) if methods else ["WEBSOCKET"]
        for method in method_names:
            registered_routes.append((path, method, route_name))
            if method == "POST" and path == FACEBOOK_WEBHOOK_PATH:
                webhook_post_registered = True

    logger.info("fastapi_registered_routes count={}", len(registered_routes))
    for path, method, route_name in sorted(registered_routes):
        logger.info(
            "fastapi_registered_route method={} path={} name={}",
            method,
            path,
            route_name,
        )
    logger.info(
        "facebook_webhook_route_check method=POST path={} registered={}",
        FACEBOOK_WEBHOOK_PATH,
        webhook_post_registered,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare runtime directories and infrastructure resources."""
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings)
    app.state.settings = settings
    app.state.manager = ConnectionManager()
    logger.info(
        "Starting {} {} in {} environment",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    log_registered_routes(app)
    init_db()
    try:
        yield
    finally:
        dispose_engine()
        logger.info("Application shutdown complete")
