"""Add optional structured Customer shipping defaults.

Revision ID: 0029_customer_default_shipping
Revises: 0028_outbound_sends
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_customer_default_shipping"
down_revision = "0028_outbound_sends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, kind in (
        ("default_shipping_ward", sa.String(255)),
        ("default_shipping_district", sa.String(255)),
        ("default_shipping_province", sa.String(255)),
        ("default_shipping_postal_code", sa.String(32)),
        ("default_shipping_country_code", sa.String(2)),
        ("default_shipping_note", sa.Text()),
    ):
        op.add_column("customers", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    for name in (
        "default_shipping_note",
        "default_shipping_country_code",
        "default_shipping_postal_code",
        "default_shipping_province",
        "default_shipping_district",
        "default_shipping_ward",
    ):
        op.drop_column("customers", name)
