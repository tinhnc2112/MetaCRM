"""Add carrier-neutral Shipment foundation.

Revision ID: 0022_shipment_foundation
Revises: 0021_order_shipping_destination
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_shipment_foundation"
down_revision = "0021_order_shipping_destination"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("shipment_number", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("recipient_name", sa.String(255), nullable=False),
        sa.Column("recipient_phone", sa.String(32), nullable=False),
        sa.Column("recipient_phone_normalized", sa.String(20), nullable=False),
        sa.Column("address_line", sa.Text(), nullable=False),
        sa.Column("ward", sa.String(255), nullable=False),
        sa.Column("district", sa.String(255), nullable=False),
        sa.Column("province", sa.String(255), nullable=False),
        sa.Column("postal_code", sa.String(32), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("delivery_note", sa.Text(), nullable=True),
        sa.Column("tracking_number", sa.String(255), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("packed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_shipments_public_id"),
        sa.UniqueConstraint("shipment_number", name="uq_shipments_shipment_number"),
        sa.CheckConstraint(
            "status IN ('ready', 'packed', 'shipped', 'delivered', 'cancelled')",
            name="ck_shipments_status",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_shipments_order_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_shipments_created_by_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"],
            name="fk_shipments_updated_by_id", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_shipments_order_created", "shipments", ["order_id", "created_at"])
    op.create_index("ix_shipments_status", "shipments", ["status"])

    op.create_table(
        "shipment_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("from_value", sa.String(32), nullable=True),
        sa.Column("to_value", sa.String(32), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_shipment_events_public_id"),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'PACKED', 'SHIPPED', 'DELIVERED', 'CANCELLED')",
            name="ck_shipment_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"], ["shipments.id"],
            name="fk_shipment_events_shipment_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_shipment_events_created_by_id", ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_shipment_events_shipment_created",
        "shipment_events", ["shipment_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("shipment_events")
    op.drop_table("shipments")
