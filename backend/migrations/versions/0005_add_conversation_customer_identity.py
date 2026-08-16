"""add customer identity fields to facebook_conversations

Revision ID: 0005_conversation_customer_identity
Revises: 0004_conversation_last_read_at
Create Date: 2026-08-11
"""

from sqlalchemy import inspect
import sqlalchemy as sa
from alembic import op

revision = "0005_conversation_customer_identity"
down_revision = "0004_conversation_last_read_at"
branch_labels = None
depends_on = None


def _conversation_column_exists(column_name: str) -> bool:
    bind = op.get_bind()
    if bind is None:
        return False

    inspector = inspect(bind)
    return any(
        column["name"] == column_name
        for column in inspector.get_columns("facebook_conversations")
    )


def upgrade() -> None:
    if not _conversation_column_exists("customer_avatar_url"):
        op.add_column(
            "facebook_conversations",
            sa.Column("customer_avatar_url", sa.String(length=2048), nullable=True),
        )


def downgrade() -> None:
    if _conversation_column_exists("customer_avatar_url"):
        op.drop_column("facebook_conversations", "customer_avatar_url")
