"""Add structured Order shipping destination snapshot.

Revision ID: 0021_order_shipping_destination
Revises: 0020_order_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_order_shipping_destination"
down_revision = "0020_order_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("shipping_recipient_name", sa.String(255)))
    op.add_column("orders", sa.Column("shipping_recipient_phone", sa.String(32)))
    op.add_column(
        "orders",
        sa.Column("shipping_recipient_phone_normalized", sa.String(20)),
    )
    op.add_column("orders", sa.Column("shipping_ward", sa.String(255)))
    op.add_column("orders", sa.Column("shipping_district", sa.String(255)))
    op.add_column("orders", sa.Column("shipping_province", sa.String(255)))
    op.add_column("orders", sa.Column("shipping_postal_code", sa.String(32)))
    op.add_column("orders", sa.Column("shipping_country_code", sa.String(2)))
    op.add_column("orders", sa.Column("shipping_note", sa.Text()))


def downgrade() -> None:
    op.drop_column("orders", "shipping_note")
    op.drop_column("orders", "shipping_country_code")
    op.drop_column("orders", "shipping_postal_code")
    op.drop_column("orders", "shipping_province")
    op.drop_column("orders", "shipping_district")
    op.drop_column("orders", "shipping_ward")
    op.drop_column("orders", "shipping_recipient_phone_normalized")
    op.drop_column("orders", "shipping_recipient_phone")
    op.drop_column("orders", "shipping_recipient_name")
