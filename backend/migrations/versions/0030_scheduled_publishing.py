"""Add durable Sheet publishing configuration and scheduled posts.

Revision ID: 0030_scheduled_publishing
Revises: 0029_customer_default_shipping
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_scheduled_publishing"
down_revision = "0029_customer_default_shipping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sheet_publishing_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spreadsheet_id", sa.String(255), nullable=False),
        sa.Column("worksheet", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_error", sa.String(500)),
        sa.Column("last_sync_result", sa.String(500)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scheduled_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.Uuid(), nullable=False, unique=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("spreadsheet_id", sa.String(255), nullable=False),
        sa.Column("worksheet", sa.String(255), nullable=False),
        sa.Column("source_row", sa.Integer()),
        sa.Column(
            "facebook_page_id",
            sa.Integer(),
            sa.ForeignKey("facebook_pages.id", ondelete="RESTRICT"),
        ),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(2048)),
        sa.Column("scheduled_for_utc", sa.DateTime(timezone=True)),
        sa.Column("source_timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("publish_started_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("facebook_post_id", sa.String(128)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_error_message", sa.String(500)),
        sa.Column("request_fingerprint", sa.String(64)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("writeback_pending", sa.Boolean(), nullable=False),
        sa.Column("writeback_error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_key", name="uq_scheduled_post_source_key"),
        sa.CheckConstraint(
            "status IN ('INVALID','READY','SCHEDULED','PUBLISHING',"
            "'PUBLISHED','FAILED','UNCERTAIN','CANCELLED')",
            name="ck_scheduled_posts_status",
        ),
    )
    op.create_index("ix_scheduled_posts_due", "scheduled_posts", ["status", "scheduled_for_utc"])
    op.create_index(
        "ix_scheduled_posts_page", "scheduled_posts", ["facebook_page_id", "scheduled_for_utc"]
    )
    op.create_index("ix_scheduled_posts_writeback", "scheduled_posts", ["writeback_pending"])


def downgrade() -> None:
    op.drop_table("scheduled_posts")
    op.drop_table("sheet_publishing_config")
