"""create customer merge tables

Revision ID: 0009_customer_merge
Revises: 0008_customer_segments
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_customer_merge"
down_revision = "0008_customer_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "facebook_conversations",
        sa.Column("merged_into_conversation_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "facebook_conversations",
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_facebook_conversations_merged_into_conversation_id",
        "facebook_conversations",
        ["merged_into_conversation_id"],
    )
    op.create_foreign_key(
        "fk_facebook_conversations_merged_into_conversation_id",
        "facebook_conversations",
        "facebook_conversations",
        ["merged_into_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "customer_merges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("primary_conversation_id", sa.Integer(), nullable=False),
        sa.Column("secondary_conversation_id", sa.Integer(), nullable=False),
        sa.Column("merged_by_user_id", sa.Integer(), nullable=True),
        sa.Column("duplicate_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("duplicate_reason", sa.Text(), nullable=False),
        sa.Column("matching_fields", sa.JSON(), nullable=False),
        sa.Column("matching_signals", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["facebook_page_id"], ["facebook_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["primary_conversation_id"], ["facebook_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secondary_conversation_id"], ["facebook_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merged_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("primary_conversation_id", "secondary_conversation_id", name="uq_customer_merges_pair"),
    )
    op.create_index("ix_customer_merges_facebook_page_id", "customer_merges", ["facebook_page_id"])
    op.create_index(
        "ix_customer_merges_primary_conversation_id",
        "customer_merges",
        ["primary_conversation_id"],
    )
    op.create_index(
        "ix_customer_merges_secondary_conversation_id",
        "customer_merges",
        ["secondary_conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_merges_secondary_conversation_id", table_name="customer_merges")
    op.drop_index("ix_customer_merges_primary_conversation_id", table_name="customer_merges")
    op.drop_index("ix_customer_merges_facebook_page_id", table_name="customer_merges")
    op.drop_table("customer_merges")

    op.drop_constraint(
        "fk_facebook_conversations_merged_into_conversation_id",
        "facebook_conversations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_facebook_conversations_merged_into_conversation_id",
        table_name="facebook_conversations",
    )
    op.drop_column("facebook_conversations", "merged_at")
    op.drop_column("facebook_conversations", "merged_into_conversation_id")
