"""create messenger tables

Revision ID: 0003_messenger
Revises: 0002_facebook_foundation
Create Date: 2026-08-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_messenger"
down_revision = "0002_facebook_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "facebook_conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.String(length=64), nullable=False),
        sa.Column("psid", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["facebook_page_id"], ["facebook_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", "psid", name="uq_facebook_conversations_page_psid"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_facebook_conversations_uuid", "facebook_conversations", ["uuid"])
    op.create_index("ix_facebook_conversations_page_id", "facebook_conversations", ["page_id"])
    op.create_index("ix_facebook_conversations_psid", "facebook_conversations", ["psid"])
    op.create_index(
        "ix_facebook_conversations_facebook_page_id",
        "facebook_conversations",
        ["facebook_page_id"],
    )

    op.create_table(
        "facebook_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("mid", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("is_from_page", sa.Boolean(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("postback_payload", sa.Text(), nullable=True),
        sa.Column("fb_timestamp_ms", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["facebook_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mid", name="uq_facebook_messages_mid"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_facebook_messages_uuid", "facebook_messages", ["uuid"])
    op.create_index("ix_facebook_messages_mid", "facebook_messages", ["mid"])
    op.create_index("ix_facebook_messages_conversation_id", "facebook_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_facebook_messages_conversation_id", table_name="facebook_messages")
    op.drop_index("ix_facebook_messages_mid", table_name="facebook_messages")
    op.drop_index("ix_facebook_messages_uuid", table_name="facebook_messages")
    op.drop_table("facebook_messages")

    op.drop_index("ix_facebook_conversations_facebook_page_id", table_name="facebook_conversations")
    op.drop_index("ix_facebook_conversations_psid", table_name="facebook_conversations")
    op.drop_index("ix_facebook_conversations_page_id", table_name="facebook_conversations")
    op.drop_index("ix_facebook_conversations_uuid", table_name="facebook_conversations")
    op.drop_table("facebook_conversations")
