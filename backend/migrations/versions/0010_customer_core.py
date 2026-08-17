"""create customer core tables (M19 Customer Core)

Revision ID: 0010_customer_core
Revises: 0009_customer_merge
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_customer_core"
down_revision = "0009_customer_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("default_address", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_customers_public_id"),
    )
    op.create_index("ix_customers_public_id", "customers", ["public_id"])
    op.create_index("ix_customers_phone", "customers", ["phone"])
    op.create_index("ix_customers_email", "customers", ["email"])

    op.create_table(
        "customer_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.Column("identity_metadata", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid", name="uq_customer_identities_uuid"),
        sa.UniqueConstraint(
            "channel", "external_id", name="uq_customer_identities_channel_external_id"
        ),
    )
    op.create_index("ix_customer_identities_uuid", "customer_identities", ["uuid"])
    op.create_index("ix_customer_identities_customer_id", "customer_identities", ["customer_id"])

    op.add_column(
        "facebook_conversations",
        sa.Column("customer_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_facebook_conversations_customer_id", "facebook_conversations", ["customer_id"]
    )
    op.create_foreign_key(
        "fk_facebook_conversations_customer_id",
        "facebook_conversations",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_facebook_conversations_customer_id",
        "facebook_conversations",
        type_="foreignkey",
    )
    op.drop_index("ix_facebook_conversations_customer_id", table_name="facebook_conversations")
    op.drop_column("facebook_conversations", "customer_id")

    op.drop_index("ix_customer_identities_customer_id", table_name="customer_identities")
    op.drop_index("ix_customer_identities_uuid", table_name="customer_identities")
    op.drop_table("customer_identities")

    op.drop_index("ix_customers_email", table_name="customers")
    op.drop_index("ix_customers_phone", table_name="customers")
    op.drop_index("ix_customers_public_id", table_name="customers")
    op.drop_table("customers")
