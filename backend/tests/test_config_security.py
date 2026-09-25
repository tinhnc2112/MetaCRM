"""Production signing configuration is validated before the app can start."""

import subprocess
import sys

import pytest
from app.core.config import Settings
from app.utils.jwt import create_access_token, decode_access_token
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError

DATABASE_URL = "mysql+pymysql://root@127.0.0.1:3307/metacrm_m0_test_e2e"


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    "secret",
    ["", " ", "development-only-change-me", "replace-with-a-long-random-secret-key",
     "short-secret", "a" * 64],
)
def test_unsafe_signing_secret_rejected_without_echo(environment: str, secret: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings.model_validate({"APP_ENV": environment, "DATABASE_URL": DATABASE_URL,
                                 "SECRET_KEY": secret})
    assert "strong explicit SECRET_KEY" in str(error.value)
    assert not secret.strip() or secret not in str(error.value)


def test_development_and_test_keep_explicit_local_default() -> None:
    for environment in ("development", "test"):
        settings = Settings.model_validate({"APP_ENV": environment, "DATABASE_URL": DATABASE_URL})
        assert settings.secret_key == "development-only-change-me"


def test_valid_production_secret_and_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    first = "a-strong-production-signing-key-0123456789-ABC"
    second = "different-strong-signing-key-9876543210-XYZ"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", first)
    get_settings.cache_clear()
    try:
        token = create_access_token("user-1")
        assert decode_access_token(token)["sub"] == "user-1"
        monkeypatch.setenv("SECRET_KEY", second)
        get_settings.cache_clear()
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)
    finally:
        get_settings.cache_clear()


def test_unsafe_production_config_fails_at_app_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "weak-production-marker")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "weak-production-marker" not in result.stdout + result.stderr
