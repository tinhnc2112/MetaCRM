"""Add Page-scoped carrier integration core.

Revision ID: 0024_carrier_integration_core
Revises: 0023_shipment_tracking_operations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_carrier_integration_core"
down_revision = "0023_shipment_tracking_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carrier_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_by_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_carrier_accounts_public_id"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_carrier_accounts_status"),
        sa.ForeignKeyConstraint(
            ["facebook_page_id"], ["facebook_pages.id"],
            name="fk_carrier_accounts_facebook_page_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_carrier_accounts_created_by_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"],
            name="fk_carrier_accounts_updated_by_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["deactivated_by_id"], ["users.id"],
            name="fk_carrier_accounts_deactivated_by_id", ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_carrier_accounts_page_status", "carrier_accounts", ["facebook_page_id", "status"]
    )
    op.create_index(
        "ix_carrier_accounts_page_provider", "carrier_accounts", ["facebook_page_id", "provider_code"]
    )
    op.add_column("shipments", sa.Column("carrier_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_shipments_carrier_account_id",
        "shipments",
        "carrier_accounts",
        ["carrier_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_shipments_carrier_account_id", "shipments", ["carrier_account_id"])


def downgrade() -> None:
    op.drop_index("ix_shipments_carrier_account_id", table_name="shipments")
    op.drop_constraint("fk_shipments_carrier_account_id", "shipments", type_="foreignkey")
    op.drop_column("shipments", "carrier_account_id")
    op.drop_table("carrier_accounts")
