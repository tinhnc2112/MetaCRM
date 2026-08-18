"""M24.1: Product catalog backend foundation.

Revision ID: 0014_product_catalog_foundation
Revises: 0013_order_backend_foundation
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_product_catalog_foundation"
down_revision = "0013_order_backend_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="VND"),
        sa.Column("sale_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_products_public_id"),
        sa.UniqueConstraint("facebook_page_id", "sku", name="uq_products_page_sku"),
        sa.ForeignKeyConstraint(["facebook_page_id"], ["facebook_pages.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_products_public_id", "products", ["public_id"], unique=False)
    op.create_index("ix_products_facebook_page_id", "products", ["facebook_page_id"], unique=False)
    op.create_index("ix_products_name", "products", ["name"], unique=False)
    op.create_index("ix_products_sku", "products", ["sku"], unique=False)
    op.create_index("ix_products_is_active", "products", ["is_active"], unique=False)
    op.create_index("ix_products_deleted_at", "products", ["deleted_at"], unique=False)

    op.add_column("order_items", sa.Column("product_id", sa.Integer(), nullable=True))
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"], unique=False)
    op.create_foreign_key(
        "fk_order_items_product_id_products",
        "order_items",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_order_items_product_id_products", "order_items", type_="foreignkey")
    op.drop_index("ix_order_items_product_id", table_name="order_items")
    op.drop_column("order_items", "product_id")

    op.drop_index("ix_products_deleted_at", table_name="products")
    op.drop_index("ix_products_is_active", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_index("ix_products_facebook_page_id", table_name="products")
    op.drop_index("ix_products_public_id", table_name="products")
    op.drop_table("products")
