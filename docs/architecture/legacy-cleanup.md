# M9 legacy cleanup and consumer inventory

The active backend entry is `backend/app/main.py` (`app.main:app` from
`backend/`), which registers `app.api.router`. It uses the MySQL SQLAlchemy
models and Alembic migrations under `backend/app/` and `backend/alembic/`.
The documented local, CI and E2E commands invoke that entry. The desktop and
extension call the active HTTP API; neither imports Python entry modules.

Before removal, we searched imports, router registration, tests, scripts,
workflow/start commands, client sources, packaging files, migration references,
and documentation. No checked-in runtime consumer invoked the following
independent sources or snapshots:

| Classification | Files | Evidence and decision |
|---|---|---|
| KEEP | `backend/app/**`, `backend/alembic/**`, `backend/tests/**`, `backend/scripts/**` | The active app, migration chain, tests and CI/E2E commands use these. |
| KEEP | `backend/requirements.txt`, `backend/__init__.py`, `docs/00_*`–`docs/25_*` | Installation or external consumers cannot be disproved for packaging files; numbered documents are product specifications, not executable replacements. |
| REMOVE | Root `main.py` | An unreferenced alias importing `app.main`; documented commands already use the active entry from `backend/`. |
| REMOVE | `backend/main.py`, `backend/config.py`, `backend/database.py`, `backend/models/order.py`, `backend/schemas/order.py`, `backend/services/{facebook_service,openai_service,order_service}.py` | A self-contained AI Sale BOT prototype with its own SQLite defaults, `create_all`, and `/webhook`; none is registered by `app.main` or imported by the active app, tests, migrations or clients. |
| REMOVE | `m29_2_wip_backup/*`, `m29_2_wip_{staged,tracked,untracked}.diff` | Unreferenced intermediate shipment copies and patch snapshots; canonical migration, implementation and tests remain under `backend/`. |

This is repository consumer evidence, not a claim about unknown external
deployments: an out-of-tree command targeting `backend/main:app` could still
exist. Operators of such deployments must switch to `app.main:app`. No active
HTTP route, database schema, business behavior or public API was changed by
the cleanup. The removed sources remain recoverable from Git history; revert
the M9 commit if an unobserved consumer is discovered.
