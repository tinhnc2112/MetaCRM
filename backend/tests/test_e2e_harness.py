"""Safety checks for the browser E2E database harness."""

from __future__ import annotations

import pytest
from scripts.e2e_harness import e2e_database_url


def test_e2e_database_requires_explicit_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METACRM_E2E", "false")
    monkeypatch.setenv(
        "METACRM_E2E_DATABASE_URL",
        "mysql+pymysql://tester:password@localhost/metacrm_e2e",
    )

    with pytest.raises(SystemExit, match="METACRM_E2E must equal true"):
        e2e_database_url()


def test_e2e_database_rejects_non_e2e_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METACRM_E2E", "true")
    monkeypatch.setenv(
        "METACRM_E2E_DATABASE_URL",
        "mysql+pymysql://tester:password@localhost/metacrm",
    )

    with pytest.raises(SystemExit, match="database name must end in _e2e"):
        e2e_database_url()


def test_e2e_database_accepts_suffix_guarded_mysql_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METACRM_E2E", "true")
    monkeypatch.setenv(
        "METACRM_E2E_DATABASE_URL",
        "mysql+pymysql://tester:password@localhost/metacrm_browser_e2e",
    )

    assert e2e_database_url().database == "metacrm_browser_e2e"
