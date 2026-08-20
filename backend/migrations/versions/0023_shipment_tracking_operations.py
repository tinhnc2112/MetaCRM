"""Add manual Shipment tracking operations.

Revision ID: 0023_shipment_tracking_operations
Revises: 0022_shipment_foundation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_shipment_tracking_operations"
down_revision = "0022_shipment_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("carrier_code", sa.String(64), nullable=True))
    op.add_column("shipments", sa.Column("carrier_name", sa.String(255), nullable=True))
    op.add_column("shipments", sa.Column("tracking_url", sa.Text(), nullable=True))
    op.add_column("shipments", sa.Column("shipping_fee", sa.Numeric(12, 2), nullable=True))
    op.add_column("shipments", sa.Column("cod_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("shipments", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("shipment_events", sa.Column("details", sa.JSON(), nullable=True))
    op.drop_constraint("ck_shipment_events_type", "shipment_events", type_="check")
    op.create_check_constraint(
        "ck_shipment_events_type",
        "shipment_events",
        "event_type IN ('CREATED', 'PACKED', 'SHIPPED', 'DELIVERED', "
        "'CANCELLED', 'TRACKING_UPDATED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_shipment_events_type", "shipment_events", type_="check")
    op.create_check_constraint(
        "ck_shipment_events_type",
        "shipment_events",
        "event_type IN ('CREATED', 'PACKED', 'SHIPPED', 'DELIVERED', 'CANCELLED')",
    )
    op.drop_column("shipment_events", "details")
    op.drop_column("shipments", "note")
    op.drop_column("shipments", "cod_amount")
    op.drop_column("shipments", "shipping_fee")
    op.drop_column("shipments", "tracking_url")
    op.drop_column("shipments", "carrier_name")
    op.drop_column("shipments", "carrier_code")
