# Active MetaCRM backend

The FastAPI application is `app.main:app` when run from this directory.
Use the [repository quick start](../README.md), [current HTTP contract](../docs/architecture/api-contract.md),
and [reproducible development guide](../docs/architecture/reproducible-baseline.md).

The historical `main.py`, `config.py`, `database.py`, `models/order.py`, and
`services/` files in this directory implement a separate AI Sale BOT prototype.
They are not the active MetaCRM application. Do not use its SQLite or `/webhook`
instructions for the active MySQL/Alembic backend.
