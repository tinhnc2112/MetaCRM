"""Declarative SQLAlchemy registry shared by all models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root metadata registry used by application models and Alembic."""
