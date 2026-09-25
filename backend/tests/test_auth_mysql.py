"""MySQL/InnoDB concurrency proof for durable refresh rotation."""

from concurrent.futures import ThreadPoolExecutor
from os import environ
from threading import Barrier
from uuid import uuid4

import pytest
from app.models.auth import RefreshSession, User
from app.services.auth import create_token_pair, rotate_refresh_token
from app.utils.password import hash_password
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def test_mysql_concurrent_refresh_only_one_rotation_commits() -> None:
    database_url = environ.get("DATABASE_URL", "")
    if environ.get("APP_ENV") != "test" or environ.get("METACRM_E2E") != "true":
        pytest.skip("requires explicit disposable MySQL test environment")
    try:
        parsed = make_url(database_url)
    except Exception:
        pytest.skip("requires disposable MySQL test DATABASE_URL")
    if (parsed.drivername != "mysql+pymysql" or parsed.database != "metacrm_m0_test_e2e"
            or parsed.host not in {"127.0.0.1", "localhost"}):
        pytest.skip("requires guarded M0 disposable MySQL database")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1 FROM refresh_sessions LIMIT 1")
        except OperationalError:
            pytest.skip("disposable MySQL unavailable or migration not applied")

        name = f"refresh-race-{uuid4().hex}"
        with Session(engine) as session:
            user = User(username=name, email=f"{name}@example.test",
                        password_hash=hash_password("test-only"))
            session.add(user)
            session.commit()
            user_id = user.id
            _, token = create_token_pair(session, user)

        barrier = Barrier(2)

        def rotate() -> bool:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                return rotate_refresh_token(session, token) is not None

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(rotate) for _ in range(2)]
                assert sorted(future.result(timeout=20) for future in futures) == [False, True]
            with Session(engine) as session:
                rows = session.scalars(select(RefreshSession).where(
                    RefreshSession.user_id == user_id
                )).all()
                assert len(rows) == 2
                assert sum(row.consumed_at is not None for row in rows) == 1
        finally:
            with Session(engine) as session:
                session.execute(delete(RefreshSession).where(RefreshSession.user_id == user_id))
                session.execute(delete(User).where(User.id == user_id))
                session.commit()
    finally:
        engine.dispose()
