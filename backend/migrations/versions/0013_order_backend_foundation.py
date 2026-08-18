"""M23.1: Customer-centric order backend foundation.

Revision ID: 0013_order_backend_foundation
Revises: 0012_customer_level_merge
Create Date: 2026-08-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_order_backend_foundation"
down_revision = "0012_customer_level_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("facebook_page_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("order_number", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payment_status", sa.String(length=32), nullable=False),
        sa.Column("shipping_status", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("shipping_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("customer_phone_snapshot", sa.String(length=32), nullable=True),
        sa.Column("customer_email_snapshot", sa.String(length=255), nullable=True),
        sa.Column("shipping_address", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_orders_public_id"),
        sa.UniqueConstraint("facebook_page_id", "order_number", name="uq_orders_page_order_number"),
        sa.ForeignKeyConstraint(["facebook_page_id"], ["facebook_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["facebook_conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_orders_public_id", "orders", ["public_id"], unique=False)
    op.create_index("ix_orders_facebook_page_id", "orders", ["facebook_page_id"], unique=False)
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"], unique=False)
    op.create_index("ix_orders_conversation_id", "orders", ["conversation_id"], unique=False)
    op.create_index("ix_orders_order_number", "orders", ["order_number"], unique=False)
    op.create_index("ix_orders_created_by_id", "orders", ["created_by_id"], unique=False)
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)
    op.create_index("ix_orders_deleted_at", "orders", ["deleted_at"], unique=False)

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_order_items_public_id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_order_items_public_id", "order_items", ["public_id"], unique=False)
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_index("ix_order_items_public_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_deleted_at", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_created_by_id", table_name="orders")
    op.drop_index("ix_orders_order_number", table_name="orders")
    op.drop_index("ix_orders_conversation_id", table_name="orders")
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_index("ix_orders_facebook_page_id", table_name="orders")
    op.drop_index("ix_orders_public_id", table_name="orders")
    op.drop_table("orders")
