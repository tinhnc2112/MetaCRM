"""M19.4: move Customer Notes / Tags ownership from conversation_id to customer_id

Revision ID: 0011_customer_notes_tags_ownership
Revises: 0010_customer_core
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_customer_notes_tags_ownership"
down_revision = "0010_customer_core"
branch_labels = None
depends_on = None


def _backfill_orphan_conversations(bind) -> None:
    """Ensure every facebook_conversations row has a customer_id before we
    propagate ownership to notes/tags (M19.3 safety net).

    Uses pure SQL Core queries instead of ORM to avoid loading columns from
    Customer model that don't yet exist at this revision (merged_into_customer_id
    is added in 0012, not 0011). This keeps migration independent from the
    evolving ORM model.
    """
    from datetime import datetime as dt
    from uuid import uuid4

    from sqlalchemy import text

    now_iso = dt.utcnow().isoformat()

    # Step 1: For each orphan conversation (customer_id IS NULL),
    # find or create a CustomerIdentity with channel=FACEBOOK, external_id=psid.
    # Then link conversation to the Customer behind that identity.
    #
    # Logic:
    # - SELECT each orphan conversation (fb_conv.customer_id IS NULL)
    # - Try to find a matching CustomerIdentity(channel, external_id)
    # - If found, use its customer_id
    # - If not found, create new Customer + CustomerIdentity, then link
    #
    # Since SQL UPDATE...FROM is not portable across MySQL/SQLite, we do this
    # in application logic within a transaction.

    cursor = bind.execute(
        text(
            """
            SELECT fc.id, fc.psid, fc.customer_name, fc.customer_avatar_url
            FROM facebook_conversations fc
            WHERE fc.customer_id IS NULL
              AND fc.deleted_at IS NULL
            """
        )
    )
    orphan_rows = cursor.fetchall()

    for fc_id, psid, customer_name, customer_avatar_url in orphan_rows:
        # Try to find existing identity
        identity_result = bind.execute(
            text(
                """
                SELECT id, customer_id FROM customer_identities
                WHERE channel = :channel AND external_id = :external_id
                LIMIT 1
                """
            ),
            {"channel": "FACEBOOK", "external_id": psid},
        ).first()

        if identity_result:
            customer_id = identity_result[1]
        else:
            # Create new Customer
            new_uuid = str(uuid4())
            bind.execute(
                text(
                    """
                    INSERT INTO customers (public_id, status, created_at, updated_at)
                    VALUES (:public_id, 'ACTIVE', :now, :now)
                    """
                ),
                {"public_id": new_uuid, "now": now_iso},
            )
            # Get the new customer_id (works on MySQL; SQLite returns last_insert_rowid)
            customer_result = bind.execute(
                text(
                    "SELECT id FROM customers WHERE public_id = :public_id LIMIT 1"
                ),
                {"public_id": new_uuid},
            ).first()
            customer_id = customer_result[0] if customer_result else None

            if customer_id:
                # Create matching identity
                identity_uuid = str(uuid4())
                bind.execute(
                    text(
                        """
                        INSERT INTO customer_identities
                        (uuid, customer_id, channel, external_id, display_name, avatar_url, first_seen_at, last_seen_at)
                        VALUES (:uuid, :customer_id, :channel, :external_id, :display_name, :avatar_url, :now, :now)
                        """
                    ),
                    {
                        "uuid": identity_uuid,
                        "customer_id": customer_id,
                        "channel": "FACEBOOK",
                        "external_id": psid,
                        "display_name": customer_name,
                        "avatar_url": customer_avatar_url,
                        "now": now_iso,
                    },
                )

        # Link conversation to customer
        if customer_id:
            bind.execute(
                text("UPDATE facebook_conversations SET customer_id = :cid WHERE id = :fc_id"),
                {"cid": customer_id, "fc_id": fc_id},
            )


def _propagate_customer_id(bind, table: str) -> None:
    """Copy facebook_conversations.customer_id onto `table.customer_id` for
    every row where it is still NULL, via a portable correlated subquery
    (works on both MySQL and SQLite, unlike UPDATE...JOIN).
    """
    bind.execute(
        sa.text(
            f"""
            UPDATE {table}
            SET customer_id = (
                SELECT fc.customer_id
                FROM facebook_conversations fc
                WHERE fc.id = {table}.conversation_id
            )
            WHERE customer_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM facebook_conversations fc
                  WHERE fc.id = {table}.conversation_id
                    AND fc.customer_id IS NOT NULL
              )
            """
        )
    )


def upgrade() -> None:
    op.add_column("customer_notes", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_index("ix_customer_notes_customer_id", "customer_notes", ["customer_id"])
    op.create_foreign_key(
        "fk_customer_notes_customer_id",
        "customer_notes",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.add_column("customer_tag_assignments", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_customer_tag_assignments_customer_id", "customer_tag_assignments", ["customer_id"]
    )
    op.create_foreign_key(
        "fk_customer_tag_assignments_customer_id",
        "customer_tag_assignments",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_customer_tag_assignments_customer_tag",
        "customer_tag_assignments",
        ["customer_id", "tag_id"],
    )

    op.add_column("customer_tag_events", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_index("ix_customer_tag_events_customer_id", "customer_tag_events", ["customer_id"])
    op.create_foreign_key(
        "fk_customer_tag_events_customer_id",
        "customer_tag_events",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="CASCADE",
    )

    bind = op.get_bind()
    _backfill_orphan_conversations(bind)
    _propagate_customer_id(bind, "customer_notes")
    _propagate_customer_id(bind, "customer_tag_assignments")
    _propagate_customer_id(bind, "customer_tag_events")

    # customer_id is intentionally left nullable at the DB level: it is
    # always set by the application for rows created from now on (see
    # services/facebook/customers.py and services/facebook/customer_tags.py),
    # but we avoid a hard NOT NULL constraint here so this migration can
    # never fail on an edge-case row (e.g. a conversation whose Page was
    # deleted before backfill could run).


def downgrade() -> None:
    op.drop_constraint("fk_customer_tag_events_customer_id", "customer_tag_events", type_="foreignkey")
    op.drop_index("ix_customer_tag_events_customer_id", table_name="customer_tag_events")
    op.drop_column("customer_tag_events", "customer_id")

    op.drop_constraint(
        "uq_customer_tag_assignments_customer_tag", "customer_tag_assignments", type_="unique"
    )
    op.drop_constraint(
        "fk_customer_tag_assignments_customer_id", "customer_tag_assignments", type_="foreignkey"
    )
    op.drop_index("ix_customer_tag_assignments_customer_id", table_name="customer_tag_assignments")
    op.drop_column("customer_tag_assignments", "customer_id")

    op.drop_constraint("fk_customer_notes_customer_id", "customer_notes", type_="foreignkey")
    op.drop_index("ix_customer_notes_customer_id", table_name="customer_notes")
    op.drop_column("customer_notes", "customer_id")
