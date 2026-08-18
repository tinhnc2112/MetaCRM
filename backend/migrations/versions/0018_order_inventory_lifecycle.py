"""Add per-OrderItem stock movement uniqueness.

Revision ID: 0018_order_inventory_lifecycle
Revises: 0017_inventory_foundation
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op

revision = "0018_order_inventory_lifecycle"
down_revision = "0017_inventory_foundation"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_stock_movements_order_item_movement_type"


def upgrade() -> None:
    op.create_unique_constraint(
        _CONSTRAINT,
        "stock_movements",
        ["order_item_id", "movement_type"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "stock_movements", type_="unique")
