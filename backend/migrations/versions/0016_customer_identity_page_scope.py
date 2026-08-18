"""Scope Facebook CustomerIdentity rows by Facebook Page.

Revision ID: 0016_customer_identity_page_scope
Revises: 0015_product_catalog_hardening
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_customer_identity_page_scope"
down_revision = "0015_product_catalog_hardening"
branch_labels = None
depends_on = None

_PAGE_COLUMN = "facebook_page_id"
_PAGE_INDEX = "ix_customer_identities_facebook_page_id"
_PAGE_FK = "fk_customer_identities_facebook_page_id"
_OLD_UNIQUE = "uq_customer_identities_channel_external_id"
_NEW_UNIQUE = "uq_customer_identities_channel_page_external_id"


def _identity_page_assignments(bind) -> dict[int, int]:
    """Return safe identity-to-Page assignments or fail before changing data."""
    rows = bind.execute(
        sa.text(
            """
            SELECT
                ci.id AS identity_id,
                COUNT(DISTINCT fc.facebook_page_id) AS page_count,
                MIN(fc.facebook_page_id) AS facebook_page_id
            FROM customer_identities ci
            LEFT JOIN facebook_conversations fc
              ON fc.customer_id = ci.customer_id
             AND fc.psid = ci.external_id
             AND ci.channel = 'FACEBOOK'
            GROUP BY ci.id
            ORDER BY ci.id
            """
        )
    ).mappings()

    assignments: dict[int, int] = {}
    unresolved: list[int] = []
    ambiguous: list[int] = []
    for row in rows:
        identity_id = int(row["identity_id"])
        page_count = int(row["page_count"])
        if page_count == 0:
            unresolved.append(identity_id)
            continue
        if page_count != 1:
            ambiguous.append(identity_id)
            continue
        assignments[identity_id] = int(row["facebook_page_id"])

    if unresolved or ambiguous:
        details: list[str] = []
        if unresolved:
            details.append(f"no matching Conversation: {unresolved}")
        if ambiguous:
            details.append(f"multiple matching Pages: {ambiguous}")
        raise RuntimeError(
            "CustomerIdentity Page backfill is unsafe ("
            + "; ".join(details)
            + "). Run M23.9B-2 preflight/split remediation before retrying."
        )
    return assignments


def _column_names(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("customer_identities")}


def _index_names(bind) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes("customer_identities")}


def _unique_names(bind) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints("customer_identities")
        if constraint.get("name")
    }


def _foreign_key_names(bind) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(bind).get_foreign_keys("customer_identities")
        if constraint.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    assignments = _identity_page_assignments(bind)

    if _PAGE_COLUMN not in _column_names(bind):
        op.add_column(
            "customer_identities",
            sa.Column(_PAGE_COLUMN, sa.Integer(), nullable=True),
        )

    for identity_id, facebook_page_id in assignments.items():
        bind.execute(
            sa.text(
                """
                UPDATE customer_identities
                SET facebook_page_id = :facebook_page_id
                WHERE id = :identity_id
                  AND facebook_page_id IS NULL
                """
            ),
            {"identity_id": identity_id, "facebook_page_id": facebook_page_id},
        )

    remaining = bind.execute(
        sa.text("SELECT COUNT(*) FROM customer_identities WHERE facebook_page_id IS NULL")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"CustomerIdentity Page backfill left {remaining} unresolved rows; "
            "run M23.9B-2 remediation before retrying."
        )

    if _PAGE_INDEX not in _index_names(bind):
        op.create_index(_PAGE_INDEX, "customer_identities", [_PAGE_COLUMN], unique=False)

    if _PAGE_FK not in _foreign_key_names(bind):
        op.create_foreign_key(
            _PAGE_FK,
            "customer_identities",
            "facebook_pages",
            [_PAGE_COLUMN],
            ["id"],
            ondelete="RESTRICT",
        )

    if _NEW_UNIQUE not in _unique_names(bind) and _NEW_UNIQUE not in _index_names(bind):
        op.create_unique_constraint(
            _NEW_UNIQUE,
            "customer_identities",
            ["channel", _PAGE_COLUMN, "external_id"],
        )

    if _OLD_UNIQUE in _unique_names(bind) or _OLD_UNIQUE in _index_names(bind):
        op.drop_constraint(_OLD_UNIQUE, "customer_identities", type_="unique")

    op.alter_column(
        "customer_identities",
        _PAGE_COLUMN,
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            """
            SELECT channel, external_id
            FROM customer_identities
            GROUP BY channel, external_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot restore global CustomerIdentity uniqueness after Page-scoped identities exist."
        )

    op.alter_column(
        "customer_identities",
        _PAGE_COLUMN,
        existing_type=sa.Integer(),
        nullable=True,
    )
    if _OLD_UNIQUE not in _unique_names(bind) and _OLD_UNIQUE not in _index_names(bind):
        op.create_unique_constraint(
            _OLD_UNIQUE,
            "customer_identities",
            ["channel", "external_id"],
        )
    if _NEW_UNIQUE in _unique_names(bind) or _NEW_UNIQUE in _index_names(bind):
        op.drop_constraint(_NEW_UNIQUE, "customer_identities", type_="unique")
    if _PAGE_FK in _foreign_key_names(bind):
        op.drop_constraint(_PAGE_FK, "customer_identities", type_="foreignkey")
    if _PAGE_INDEX in _index_names(bind):
        op.drop_index(_PAGE_INDEX, table_name="customer_identities")
    op.drop_column("customer_identities", _PAGE_COLUMN)
