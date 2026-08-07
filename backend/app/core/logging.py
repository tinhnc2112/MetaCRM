"""Structured application logging configuration."""

import sys

from loguru import logger

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure console and rotating file log sinks exactly once per process."""
    logger.remove()
    level = settings.log_level.upper()
    logger.add(
        sys.stderr,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}",
        backtrace=settings.debug,
        diagnose=settings.debug,
    )
    logger.add(
        settings.log_dir / "application.log",
        level=level,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
