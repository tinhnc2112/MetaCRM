"""M19.5: Customer-level merge (never only Conversation)

Revision ID: 0012_customer_level_merge
Revises: 0011_customer_notes_tags_ownership
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_customer_level_merge"
down_revision = "0011_customer_notes_tags_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("merged_into_customer_id", sa.Integer(), nullable=True))
    op.add_column("customers", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_customers_merged_into_customer_id", "customers", ["merged_into_customer_id"])
    op.create_foreign_key(
        "fk_customers_merged_into_customer_id",
        "customers",
        "customers",
        ["merged_into_customer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("customer_merges", sa.Column("primary_customer_id", sa.Integer(), nullable=True))
    op.add_column("customer_merges", sa.Column("secondary_customer_id", sa.Integer(), nullable=True))
    op.create_index("ix_customer_merges_primary_customer_id", "customer_merges", ["primary_customer_id"])
    op.create_index(
        "ix_customer_merges_secondary_customer_id", "customer_merges", ["secondary_customer_id"]
    )
    op.create_foreign_key(
        "fk_customer_merges_primary_customer_id",
        "customer_merges",
        "customers",
        ["primary_customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_customer_merges_secondary_customer_id",
        "customer_merges",
        "customers",
        ["secondary_customer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    # Backfill existing (pre-M19.5) merge rows: resolve the Customer behind
    # each recorded conversation pair via a portable correlated subquery.
    bind.execute(
        sa.text(
            """
            UPDATE customer_merges
            SET primary_customer_id = (
                SELECT fc.customer_id FROM facebook_conversations fc
                WHERE fc.id = customer_merges.primary_conversation_id
            )
            WHERE primary_customer_id IS NULL
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE customer_merges
            SET secondary_customer_id = (
                SELECT fc.customer_id FROM facebook_conversations fc
                WHERE fc.id = customer_merges.secondary_conversation_id
            )
            WHERE secondary_customer_id IS NULL
            """
        )
    )

    op.create_unique_constraint(
        "uq_customer_merges_customer_pair",
        "customer_merges",
        ["primary_customer_id", "secondary_customer_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_customer_merges_customer_pair", "customer_merges", type_="unique")

    op.drop_constraint(
        "fk_customer_merges_secondary_customer_id", "customer_merges", type_="foreignkey"
    )
    op.drop_constraint("fk_customer_merges_primary_customer_id", "customer_merges", type_="foreignkey")
    op.drop_index("ix_customer_merges_secondary_customer_id", table_name="customer_merges")
    op.drop_index("ix_customer_merges_primary_customer_id", table_name="customer_merges")
    op.drop_column("customer_merges", "secondary_customer_id")
    op.drop_column("customer_merges", "primary_customer_id")

    op.drop_constraint("fk_customers_merged_into_customer_id", "customers", type_="foreignkey")
    op.drop_index("ix_customers_merged_into_customer_id", table_name="customers")
    op.drop_column("customers", "merged_at")
    op.drop_column("customers", "merged_into_customer_id")
