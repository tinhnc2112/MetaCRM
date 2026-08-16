"""Focused tests for migration 0005 conversation customer identity."""

from __future__ import annotations

import importlib
from types import SimpleNamespace


migration_0005 = importlib.import_module(
    "migrations.versions.0005_add_conversation_customer_identity"
)


class _FakeInspector:
    def __init__(self, columns: list[dict[str, str]]):
        self._columns = columns

    def get_columns(self, table_name: str):  # noqa: D401 - alembic-style fake
        assert table_name == "facebook_conversations"
        return self._columns


def test_upgrade_skips_existing_customer_avatar_url(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(migration_0005.op, "get_bind", lambda: SimpleNamespace())
    monkeypatch.setattr(
        migration_0005,
        "inspect",
        lambda bind: _FakeInspector([{"name": "customer_avatar_url"}]),
    )
    monkeypatch.setattr(
        migration_0005.op,
        "add_column",
        lambda table_name, column: calls.append((table_name, column.name)),
    )

    migration_0005.upgrade()

    assert calls == []


def test_upgrade_adds_customer_avatar_url_when_missing(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(migration_0005.op, "get_bind", lambda: SimpleNamespace())
    monkeypatch.setattr(migration_0005, "inspect", lambda bind: _FakeInspector([]))
    monkeypatch.setattr(
        migration_0005.op,
        "add_column",
        lambda table_name, column: calls.append((table_name, column.name)),
    )

    migration_0005.upgrade()

    assert calls == [("facebook_conversations", "customer_avatar_url")]


def test_downgrade_drops_customer_avatar_url_only_when_present(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(migration_0005.op, "get_bind", lambda: SimpleNamespace())
    monkeypatch.setattr(
        migration_0005,
        "inspect",
        lambda bind: _FakeInspector([{"name": "customer_avatar_url"}]),
    )
    monkeypatch.setattr(
        migration_0005.op,
        "drop_column",
        lambda table_name, column_name: calls.append(f"{table_name}.{column_name}"),
    )

    migration_0005.downgrade()

    assert calls == ["facebook_conversations.customer_avatar_url"]
