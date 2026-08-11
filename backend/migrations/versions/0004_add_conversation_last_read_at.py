"""add last_read_at to facebook_conversations

Revision ID: 0004_conversation_last_read_at
Revises: 0003_messenger
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_conversation_last_read_at"
down_revision = "0003_messenger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "facebook_conversations",
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("facebook_conversations", "last_read_at")
