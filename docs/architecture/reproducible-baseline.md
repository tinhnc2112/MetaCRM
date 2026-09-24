# M0: reproducible development baseline

Use Python 3.13 (`.python-version` and `pyproject.toml`), Node 24 and the checked-in dependency locks. Run commands from the repository root unless a `cd` is shown. This baseline does not change business rules or assume that a developer's MySQL installation is missing. It supplies its own disposable MySQL for Work and CI.

## Install

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements/dev.lock.txt
cd desktop && npm ci && cd ..
cd extension && npm ci && cd ..
```

On Windows PowerShell use `py -3.13 -m venv .venv`, then `.\.venv\Scripts\python.exe` for the commands below. Run `npm ci` from each client directory. `dev.lock.txt` was resolved with `uv pip compile backend/requirements/dev.txt --python-version 3.13 --universal -o backend/requirements/dev.lock.txt`; regenerate intentionally when updating dependency ranges, then rerun the full baseline. `package-lock.json` files are the client locks. No Facebook or carrier credentials are needed.

## Disposable database and migrations

Requires Docker Compose. The test container uses only in-memory storage, binds port **3307 on loopback** (leaves workstation port 3306 alone) and uses an empty password *only inside this isolated development container*. The name `metacrm_m0_test_e2e` satisfies both the E2E harness's `_e2e` safety guard and the existing MySQL concurrency test's `test` URL guard. Never point these commands at a developer or production database: `prepare` intentionally resets tables in its suffix-guarded `_e2e` target. Stop it with `docker compose -f compose.m0.yml down`; data vanishes with the container.

```bash
docker compose -f compose.m0.yml up -d --wait
export METACRM_E2E=true APP_ENV=test
export DATABASE_URL='mysql+pymysql://root@127.0.0.1:3307/metacrm_m0_test_e2e'
export METACRM_E2E_DATABASE_URL="$DATABASE_URL"
.venv/bin/python backend/scripts/e2e_harness.py prepare > /dev/null
cd backend
../.venv/bin/python -m scripts.m0_seed_mysql
../.venv/bin/python -m alembic heads
../.venv/bin/python -m alembic current --check-heads
cd ..
```

In PowerShell set `$env:METACRM_E2E='true'`, `$env:APP_ENV='test'`, `$env:DATABASE_URL='mysql+pymysql://root@127.0.0.1:3307/metacrm_m0_test_e2e'`, and `$env:METACRM_E2E_DATABASE_URL=$env:DATABASE_URL`. For a clean migration run, repeat `prepare` only on this dedicated container. The Alembic revision head observed at audit was `0026_fb_webhook_subscription`; `current --check-heads` checks the actual migrated state. No migration is applied to any developer or production DB by this guide.

## Verification commands

```bash
.venv/bin/python -m pytest -q backend/tests -rx -rs
.venv/bin/python -m pytest -q backend/tests/test_waybills.py::test_mysql_two_session_finalization_serializes_current_pointer -rs
.venv/bin/python scripts/check_ruff_baseline.py
cd desktop && npm run build && cd ..
cd extension && npm run build && cd ..
```

The MySQL concurrency case needs the migrated and seeded disposable database above; if it **skips**, integration verification is incomplete (CI fails on this skip). The full backend suite includes startup tests that require this disposable MySQL, while most feature tests create separate SQLite fixtures. `test_webhook.py::test_parse_read_event` documents an existing contract mismatch: it expects a read receipt event while the current parser ignores read receipts. The test has a strict `xfail` limited to `AssertionError`: an unexpected pass fails the suite, and import or other runtime failures remain failures. Fixing that product contract is outside M0.

The Ruff baseline is 365 diagnostics with Ruff 0.16.8, measured at M0. CI compares the per-rule diagnostic counts for `backend` with that baseline; it does **not** guarantee that every changed Python file is individually lint-clean. For detailed backlog inspection run `.venv/bin/python -m ruff check backend --no-cache` (nonzero is expected until the backlog is resolved). Check new Python files directly during review, for example with `.venv/bin/python -m ruff check path/to/new_file.py --no-cache`. Build outputs, caches and local `.venv` must not be committed.

`.github/workflows/m0-baseline.yml` runs the same setup using a fresh MySQL 8.4 service on CI port 3306; it never connects to the developer workstation. It does not run browser Playwright E2E; that suite requires browser binaries and a separate test pass. Migration/schema changes require a forward migration and a separate rollback/roll-forward rehearsal on disposable data, not an assumption of reversible MySQL DDL.

## Environment findings and limitations

The earlier audit's `127.0.0.1:3306` failure concerned its isolated Work environment only. It is not evidence about a Windows developer machine. On Python 3.13, unbounded FastAPI resolution selected 0.141.1 and changed router introspection; pinning the repository's existing 0.115.6 release restores its route-registration test without changing application code. Alembic `heads` can be inspected without MySQL; generating the full offline SQL fails at migration `0005` because that migration inspects the live connection, so use the disposable MySQL for `upgrade` and `current`. Browser E2E, production integration, live Facebook/carrier actions, production data, load and restore testing are outside M0. If a product test fails with the disposable MySQL available, record its assertion and keep the repair in a separate milestone unless it is caused by this setup.
