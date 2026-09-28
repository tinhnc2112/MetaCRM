"""Reserve outbound Graph sends before network I/O.

Revision ID: 0028_outbound_sends
Revises: 0027_refresh_sessions
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_outbound_sends"
down_revision = "0027_refresh_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbound_sends",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["facebook_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["facebook_messages.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("operation_id", name="uq_outbound_sends_operation_id"),
        sa.UniqueConstraint("message_id", name="uq_outbound_sends_message_id"),
    )
    op.create_index("ix_outbound_sends_conversation_id", "outbound_sends", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_outbound_sends_conversation_id", table_name="outbound_sends")
    op.drop_table("outbound_sends")
