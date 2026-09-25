from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import RefreshSession, Role, User
from app.utils.jwt import create_refresh_token, decode_access_token
from app.utils.password import hash_password, verify_password
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    database_session = local_session()
    database_session.add(Role(name="staff", description="Standard staff access"))
    database_session.add(
        User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Alice Example",
        )
    )
    database_session.commit()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@pytest.fixture()
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr("app.startup.lifecycle.init_db", lambda: None)

    def override_db() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_password_hashing() -> None:
    password_hash = hash_password("a-safe-password")
    assert password_hash != "a-safe-password"
    assert password_hash.startswith("$2")


def test_password_verification() -> None:
    password_hash = hash_password("a-safe-password")
    assert verify_password("a-safe-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_login_success(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-password"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_failure(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_protected_endpoint(client: TestClient) -> None:
    unauthorized = client.get("/api/v1/auth/me")
    assert unauthorized.status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-password"}
    )
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert "password_hash" not in response.json()


def test_refresh_token(client: TestClient, session: Session) -> None:
    login = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-password"}
    )
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]
    assert response.json()["refresh_token"] != login.json()["refresh_token"]
    session.expire_all()
    rows = session.query(RefreshSession).order_by(RefreshSession.id).all()
    assert len(rows) == 2
    assert rows[0].consumed_at is not None
    assert rows[1].consumed_at is None and rows[1].revoked_at is None
    assert rows[1].token_id == decode_access_token(response.json()["refresh_token"])["jti"]
    assert client.post("/api/v1/auth/refresh", json={
        "refresh_token": login.json()["refresh_token"]
    }).status_code == 401


def test_logout_durably_revokes_refresh_but_preserves_access_contract(
    client: TestClient, session: Session, caplog: pytest.LogCaptureFixture,
) -> None:
    login = client.post("/api/v1/auth/login", json={
        "username": "alice", "password": "correct-password"
    }).json()
    token = login["refresh_token"]
    stored = session.query(RefreshSession).one()
    assert stored.token_id == decode_access_token(token)["jti"]
    assert token not in str(stored.__dict__)
    assert client.post("/api/v1/auth/logout", json={"refresh_token": token}).status_code == 204
    session.expire_all()
    assert session.query(RefreshSession).one().revoked_at is not None
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {login['access_token']}"
    }).status_code == 200
    assert token not in caplog.text
    assert login["access_token"] not in caplog.text


def test_refresh_rejects_invalid_expired_and_unissued_tokens(
    client: TestClient, session: Session,
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    settings = get_settings()
    old = jwt.encode({
        "sub": str(user.uuid), "type": "refresh", "jti": str(uuid4()),
        "exp": datetime.now(UTC) - timedelta(seconds=1),
    }, settings.secret_key, algorithm=settings.jwt_algorithm)
    invalid = ["invalid", old, create_refresh_token(str(user.uuid))]
    for token in invalid:
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 401
    login = client.post("/api/v1/auth/login", json={
        "username": "alice", "password": "correct-password"
    }).json()
    stored = session.query(RefreshSession).one()
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert client.post("/api/v1/auth/refresh", json={
        "refresh_token": login["refresh_token"]
    }).status_code == 401


def test_inactive_user_and_wrong_token_type_cannot_rotate(
    client: TestClient, session: Session,
) -> None:
    login = client.post("/api/v1/auth/login", json={
        "username": "alice", "password": "correct-password"
    }).json()
    assert client.post("/api/v1/auth/refresh", json={
        "refresh_token": login["access_token"]
    }).status_code == 401
    user = session.query(User).filter(User.username == "alice").one()
    user.is_active = False
    session.commit()
    assert client.post("/api/v1/auth/refresh", json={
        "refresh_token": login["refresh_token"]
    }).status_code == 401
