"""create customer tag tables

Revision ID: 0007_customer_tags
Revises: 0006_customer_notes
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_customer_tags"
down_revision = "0006_customer_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["facebook_page_id"], ["facebook_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("facebook_page_id", "name", name="uq_customer_tags_page_name"),
        sa.UniqueConstraint("facebook_page_id", "slug", name="uq_customer_tags_page_slug"),
    )
    op.create_index("ix_customer_tags_facebook_page_id", "customer_tags", ["facebook_page_id"])
    op.create_index("ix_customer_tags_slug", "customer_tags", ["slug"])

    op.create_table(
        "customer_tag_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["facebook_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["customer_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "tag_id", name="uq_customer_tag_assignments_conversation_tag"),
    )
    op.create_index(
        "ix_customer_tag_assignments_conversation_id",
        "customer_tag_assignments",
        ["conversation_id"],
    )
    op.create_index("ix_customer_tag_assignments_tag_id", "customer_tag_assignments", ["tag_id"])

    op.create_table(
        "customer_tag_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("tag_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("tag_slug_snapshot", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["facebook_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["customer_tags.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_tag_events_conversation_id",
        "customer_tag_events",
        ["conversation_id"],
    )
    op.create_index("ix_customer_tag_events_tag_id", "customer_tag_events", ["tag_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_tag_events_tag_id", table_name="customer_tag_events")
    op.drop_index("ix_customer_tag_events_conversation_id", table_name="customer_tag_events")
    op.drop_table("customer_tag_events")

    op.drop_index("ix_customer_tag_assignments_tag_id", table_name="customer_tag_assignments")
    op.drop_index(
        "ix_customer_tag_assignments_conversation_id",
        table_name="customer_tag_assignments",
    )
    op.drop_table("customer_tag_assignments")

    op.drop_index("ix_customer_tags_slug", table_name="customer_tags")
    op.drop_index("ix_customer_tags_facebook_page_id", table_name="customer_tags")
    op.drop_table("customer_tags")
