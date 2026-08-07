"""ASGI entry point for MetaCRM."""

from backend.app.main import create_app

app = create_app()
