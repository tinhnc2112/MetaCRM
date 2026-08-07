# MetaCRM Backend

Infrastructure-only FastAPI foundation for MetaCRM.

## Quick start

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements\dev.txt
Copy-Item .env.example .env
Set-Location backend
uvicorn app.main:app --reload
```

The service exposes `GET /health` and `GET /version`. Apply schema changes with Alembic using `alembic -c backend/alembic.ini upgrade head`.
