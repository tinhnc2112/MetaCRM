"""Database initialization and connectivity checks.

This module deliberately does not create schemas or seed records. Alembic owns
all schema changes.
"""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine


def check_database_connection() -> None:
    """Raise SQLAlchemyError when MySQL cannot accept a basic query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise


def init_db() -> None:
    """Verify that the configured database is reachable at application startup."""
    check_database_connection()
