"""create facebook foundation tables

Revision ID: 0002_facebook_foundation
Revises: 0001_authentication
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_facebook_foundation"
down_revision = "0001_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "facebook_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("facebook_user_id", sa.String(length=64), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("facebook_user_id", name="uq_facebook_accounts_facebook_user_id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_facebook_accounts_facebook_user_id", "facebook_accounts", ["facebook_user_id"])
    op.create_index("ix_facebook_accounts_user_id", "facebook_accounts", ["user_id"])
    op.create_index("ix_facebook_accounts_uuid", "facebook_accounts", ["uuid"])

    op.create_table(
        "facebook_pages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("facebook_account_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("picture_url", sa.String(length=2048), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["facebook_account_id"], ["facebook_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", name="uq_facebook_pages_page_id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_facebook_pages_page_id", "facebook_pages", ["page_id"])
    op.create_index("ix_facebook_pages_uuid", "facebook_pages", ["uuid"])

    op.create_table(
        "facebook_oauth_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_facebook_oauth_states_state_hash", "facebook_oauth_states", ["state_hash"])
    op.create_index("ix_facebook_oauth_states_uuid", "facebook_oauth_states", ["uuid"])

    op.create_table(
        "user_page_contexts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["facebook_page_id"], ["facebook_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_page_contexts_user_id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_user_page_contexts_uuid", "user_page_contexts", ["uuid"])


def downgrade() -> None:
    op.drop_index("ix_user_page_contexts_uuid", table_name="user_page_contexts")
    op.drop_table("user_page_contexts")
    op.drop_index("ix_facebook_oauth_states_uuid", table_name="facebook_oauth_states")
    op.drop_index("ix_facebook_oauth_states_state_hash", table_name="facebook_oauth_states")
    op.drop_table("facebook_oauth_states")
    op.drop_index("ix_facebook_pages_uuid", table_name="facebook_pages")
    op.drop_index("ix_facebook_pages_page_id", table_name="facebook_pages")
    op.drop_table("facebook_pages")
    op.drop_index("ix_facebook_accounts_uuid", table_name="facebook_accounts")
    op.drop_index("ix_facebook_accounts_user_id", table_name="facebook_accounts")
    op.drop_index("ix_facebook_accounts_facebook_user_id", table_name="facebook_accounts")
    op.drop_table("facebook_accounts")
