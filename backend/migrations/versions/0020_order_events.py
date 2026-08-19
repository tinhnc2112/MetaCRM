"""Add append-only Order business events.

Revision ID: 0020_order_events
Revises: 0019_order_creation_idempotency
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_order_events"
down_revision = "0019_order_creation_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_value", sa.String(length=32), nullable=True),
        sa.Column("to_value", sa.String(length=32), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_order_events_public_id"),
        sa.CheckConstraint(
            "event_type IN ('ORDER_CREATED', 'ORDER_CONFIRMED', 'ORDER_CANCELLED', "
            "'PAYMENT_STATUS_CHANGED', 'SHIPPING_STATUS_CHANGED')",
            name="ck_order_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_events_order_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_order_events_created_by_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_order_events_order_created",
        "order_events",
        ["order_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("order_events")
