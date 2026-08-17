"""create customer segment tables

Revision ID: 0008_customer_segments
Revises: 0007_customer_tags
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_customer_segments"
down_revision = "0007_customer_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["facebook_page_id"], ["facebook_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_segments_facebook_page_id", "customer_segments", ["facebook_page_id"])
    op.create_index("ix_customer_segments_active", "customer_segments", ["active"])

    op.create_table(
        "customer_segment_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("operator", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["segment_id"], ["customer_segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_segment_rules_segment_id", "customer_segment_rules", ["segment_id"])
    op.create_index(
        "ix_customer_segment_rules_sort_order",
        "customer_segment_rules",
        ["segment_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_segment_rules_sort_order", table_name="customer_segment_rules")
    op.drop_index("ix_customer_segment_rules_segment_id", table_name="customer_segment_rules")
    op.drop_table("customer_segment_rules")

    op.drop_index("ix_customer_segments_active", table_name="customer_segments")
    op.drop_index("ix_customer_segments_facebook_page_id", table_name="customer_segments")
    op.drop_table("customer_segments")
