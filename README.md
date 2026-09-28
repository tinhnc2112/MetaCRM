# MetaCRM

FastAPI/MySQL CRM backend, Electron desktop and browser extension. The active
backend is `backend/app/main.py`; the API is mounted at `/api/v1`.

## Development

Use Python 3.13, Node 24 and the checked-in dependency locks. From the repository root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements\dev.lock.txt
Copy-Item .env.example .env
```

Configure `DATABASE_URL` for a development MySQL database in `.env`. Apply
migrations before starting the server (no tables are created on startup):

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

With the server running, `GET /api/v1/system/health` is public liveness,
`GET /api/v1/system/health/database` checks database readiness, and both
`GET /version` and `GET /api/v1/system/version` expose release metadata.
There is no root `/health` route. API paths are fixed in code; the former
`API_V1_PREFIX` environment setting never affected routing and is no longer
advertised.

See [active API contracts](docs/architecture/api-contract.md) and the
[disposable MySQL and verification guide](docs/architecture/reproducible-baseline.md)
for tests, lint, migrations and client builds. The historical feature plan
under `docs/` includes capabilities not yet implemented by this server.
