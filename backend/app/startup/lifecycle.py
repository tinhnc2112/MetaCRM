"""FastAPI lifespan hooks."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.init_db import init_db
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare runtime directories and infrastructure resources."""
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings)
    app.state.settings = settings
    logger.info("Starting {} {} in {} environment", settings.app_name, settings.app_version, settings.environment)
    init_db()
    try:
        yield
    finally:
        dispose_engine()
        logger.info("Application shutdown complete")
