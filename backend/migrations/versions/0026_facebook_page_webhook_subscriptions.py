"""Track Facebook Page Messenger webhook subscriptions.

Revision ID: 0026_fb_webhook_subscription
Revises: 0025_external_waybill_foundation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_fb_webhook_subscription"
down_revision = "0025_external_waybill_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "facebook_pages",
        sa.Column(
            "webhook_subscription_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "facebook_pages",
        sa.Column(
            "webhook_subscription_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "facebook_pages",
        sa.Column(
            "webhook_subscription_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "facebook_pages",
        sa.Column("webhook_subscribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "facebook_pages",
        sa.Column("webhook_subscription_last_error", sa.String(length=1000), nullable=True),
    )
    op.create_check_constraint(
        "ck_facebook_pages_webhook_subscription_status",
        "facebook_pages",
        "webhook_subscription_status IN ('pending', 'subscribed', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_facebook_pages_webhook_subscription_status",
        "facebook_pages",
        type_="check",
    )
    op.drop_column("facebook_pages", "webhook_subscription_last_error")
    op.drop_column("facebook_pages", "webhook_subscribed_at")
    op.drop_column("facebook_pages", "webhook_subscription_last_attempt_at")
    op.drop_column("facebook_pages", "webhook_subscription_attempt_count")
    op.drop_column("facebook_pages", "webhook_subscription_status")
