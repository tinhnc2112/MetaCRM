"""Add the Page-scoped Product inventory foundation.

Revision ID: 0017_inventory_foundation
Revises: 0016_customer_identity_page_scope
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_inventory_foundation"
down_revision = "0016_customer_identity_page_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("track_inventory", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "product_inventories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity_on_hand", sa.BigInteger(), nullable=False),
        sa.Column("tracking_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_product_inventories_public_id"),
        sa.UniqueConstraint("product_id", name="uq_product_inventories_product_id"),
        sa.CheckConstraint(
            "quantity_on_hand >= 0", name="ck_product_inventories_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_inventories_product_id",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("order_item_id", sa.Integer(), nullable=True),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("quantity_delta", sa.BigInteger(), nullable=False),
        sa.Column("quantity_before", sa.BigInteger(), nullable=False),
        sa.Column("quantity_after", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_stock_movements_public_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_stock_movements_idempotency_key"),
        sa.CheckConstraint(
            "movement_type IN ('OPENING', 'ADJUSTMENT', 'ORDER_OUT', 'ORDER_CANCEL_RESTORE')",
            name="ck_stock_movements_type",
        ),
        sa.CheckConstraint(
            "quantity_delta <> 0 OR movement_type = 'OPENING'",
            name="ck_stock_movements_delta",
        ),
        sa.CheckConstraint(
            "quantity_before >= 0", name="ck_stock_movements_before_nonnegative"
        ),
        sa.CheckConstraint(
            "quantity_after >= 0", name="ck_stock_movements_after_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_stock_movements_product_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_stock_movements_order_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            name="fk_stock_movements_order_item_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_stock_movements_created_by_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_stock_movements_product_created",
        "stock_movements",
        ["product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_stock_movements_order_id", "stock_movements", ["order_id"], unique=False
    )
    op.create_index(
        "ix_stock_movements_order_item_id",
        "stock_movements",
        ["order_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("stock_movements")
    op.drop_table("product_inventories")
    op.drop_column("products", "track_inventory")
