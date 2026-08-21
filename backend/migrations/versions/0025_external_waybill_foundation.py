"""Add external waybill and carrier operation foundation.

Revision ID: 0025_external_waybill_foundation
Revises: 0024_carrier_integration_core
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_external_waybill_foundation"
down_revision = "0024_carrier_integration_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_waybills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("carrier_account_id", sa.Integer(), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("account_public_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("account_display_name_snapshot", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("tracking_number", sa.String(255), nullable=True),
        sa.Column("tracking_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_external_waybills_public_id"),
        sa.UniqueConstraint(
            "carrier_account_id", "external_id", name="uq_external_waybills_account_external_id"
        ),
        sa.CheckConstraint(
            "status IN ('created', 'cancelled', 'unknown')", name="ck_external_waybills_status"
        ),
        sa.ForeignKeyConstraint(
            ["facebook_page_id"],
            ["facebook_pages.id"],
            name="fk_external_waybills_facebook_page_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name="fk_external_waybills_shipment_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["carrier_account_id"],
            ["carrier_accounts.id"],
            name="fk_external_waybills_carrier_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_external_waybills_created_by_id",
            ondelete="SET NULL",
        ),
    )
    op.add_column(
        "shipments", sa.Column("current_external_waybill_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_shipments_current_external_waybill_id",
        "shipments",
        "external_waybills",
        ["current_external_waybill_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_shipments_current_external_waybill_id",
        "shipments",
        ["current_external_waybill_id"],
        unique=True,
    )
    op.create_index(
        "ix_external_waybills_page_created", "external_waybills", ["facebook_page_id", "created_at"]
    )
    op.create_index(
        "ix_external_waybills_tracking", "external_waybills", ["provider_code", "tracking_number"]
    )

    op.create_table(
        "carrier_operations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("carrier_account_id", sa.Integer(), nullable=False),
        sa.Column("external_waybill_id", sa.Integer(), nullable=True),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("account_public_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("account_display_name_snapshot", sa.String(255), nullable=False),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("response_snapshot", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("attempted_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_carrier_operations_public_id"),
        sa.UniqueConstraint(
            "facebook_page_id",
            "shipment_id",
            "carrier_account_id",
            "operation_type",
            "idempotency_key",
            name="uq_carrier_operations_scope_idempotency",
        ),
        sa.CheckConstraint(
            "operation_type IN ('CREATE_WAYBILL', 'CANCEL_WAYBILL')",
            name="ck_carrier_operations_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'unknown')",
            name="ck_carrier_operations_status",
        ),
        sa.ForeignKeyConstraint(
            ["facebook_page_id"],
            ["facebook_pages.id"],
            name="fk_carrier_operations_facebook_page_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name="fk_carrier_operations_shipment_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["carrier_account_id"],
            ["carrier_accounts.id"],
            name="fk_carrier_operations_carrier_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_waybill_id"],
            ["external_waybills.id"],
            name="fk_carrier_operations_external_waybill_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["attempted_by_id"],
            ["users.id"],
            name="fk_carrier_operations_attempted_by_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_carrier_operations_shipment_created",
        "carrier_operations",
        ["shipment_id", "created_at", "id"],
    )
    op.create_index(
        "ix_carrier_operations_page_created",
        "carrier_operations",
        ["facebook_page_id", "created_at", "id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "carrier_operations" in inspector.get_table_names():
        op.drop_table("carrier_operations")
        inspector = sa.inspect(bind)

    if "shipments" not in inspector.get_table_names():
        raise RuntimeError(
            "Cannot downgrade 0025_external_waybill_foundation: required table "
            "'shipments' is missing."
        )

    shipment_foreign_keys = {
        foreign_key["name"] for foreign_key in inspector.get_foreign_keys("shipments")
    }
    if "fk_shipments_current_external_waybill_id" in shipment_foreign_keys:
        op.drop_constraint(
            "fk_shipments_current_external_waybill_id", "shipments", type_="foreignkey"
        )
        inspector = sa.inspect(bind)

    shipment_indexes = {index["name"] for index in inspector.get_indexes("shipments")}
    if "ix_shipments_current_external_waybill_id" in shipment_indexes:
        op.drop_index("ix_shipments_current_external_waybill_id", table_name="shipments")
        inspector = sa.inspect(bind)

    shipment_columns = {column["name"] for column in inspector.get_columns("shipments")}
    if "current_external_waybill_id" in shipment_columns:
        op.drop_column("shipments", "current_external_waybill_id")
        inspector = sa.inspect(bind)

    if "external_waybills" in inspector.get_table_names():
        op.drop_table("external_waybills")
