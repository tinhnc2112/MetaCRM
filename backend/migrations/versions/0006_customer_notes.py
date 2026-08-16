"""create customer_notes table

Revision ID: 0006_customer_notes
Revises: 0005_conversation_customer_identity
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_customer_notes"
down_revision = "0005_conversation_customer_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["facebook_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(
        "ix_customer_notes_conversation_id",
        "customer_notes",
        ["conversation_id"],
    )
    op.create_index("ix_customer_notes_user_id", "customer_notes", ["user_id"])
    op.create_index("ix_customer_notes_uuid", "customer_notes", ["uuid"])


def downgrade() -> None:
    op.drop_index("ix_customer_notes_uuid", table_name="customer_notes")
    op.drop_index("ix_customer_notes_user_id", table_name="customer_notes")
    op.drop_index("ix_customer_notes_conversation_id", table_name="customer_notes")
    op.drop_table("customer_notes")
