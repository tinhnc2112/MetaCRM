# Active MetaCRM backend

The FastAPI application is `app.main:app` when run from this directory.
Use the [repository quick start](../README.md), [current HTTP contract](../docs/architecture/api-contract.md),
and [reproducible development guide](../docs/architecture/reproducible-baseline.md).

The independent AI Sale BOT prototype was removed in M9. Its SQLite and
`/webhook` instructions never applied to the active MySQL/Alembic backend;
the historical implementation remains available in Git history.
