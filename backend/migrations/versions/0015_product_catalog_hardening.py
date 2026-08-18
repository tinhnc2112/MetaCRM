"""M24.2: remove the redundant Product public UUID index.

Revision ID: 0015_product_catalog_hardening
Revises: 0014_product_catalog_foundation
Create Date: 2026-08-18
"""

from alembic import op

revision = "0015_product_catalog_hardening"
down_revision = "0014_product_catalog_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_products_public_id", table_name="products")


def downgrade() -> None:
    op.create_index("ix_products_public_id", "products", ["public_id"], unique=False)
