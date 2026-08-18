"""Add durable request idempotency to Order creation.

Revision ID: 0019_order_creation_idempotency
Revises: 0018_order_inventory_lifecycle
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_order_creation_idempotency"
down_revision = "0018_order_inventory_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("idempotency_key", sa.String(length=36), nullable=True))
    op.add_column("orders", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_orders_page_creator_idempotency_key",
        "orders",
        ["facebook_page_id", "created_by_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_orders_page_creator_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "request_fingerprint")
    op.drop_column("orders", "idempotency_key")
