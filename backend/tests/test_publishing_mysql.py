"""Guarded InnoDB proof that two workers cannot claim one schedule twice."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from os import environ
from threading import Barrier
from uuid import uuid4

import pytest
from app.models.facebook import FacebookPage
from app.models.publishing import ScheduledPost, source_identity_key
from app.services.publishing.worker import claim_due
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def test_two_mysql_workers_one_claim():
    url = environ.get("DATABASE_URL", "")
    try:
        target = make_url(url)
    except Exception:
        pytest.skip("requires guarded disposable MySQL")
    if (
        environ.get("APP_ENV") != "test"
        or environ.get("METACRM_E2E") != "true"
        or target.drivername != "mysql+pymysql"
        or target.database != "metacrm_m0_test_e2e"
        or target.host not in {"localhost", "127.0.0.1"}
    ):
        pytest.skip("requires guarded disposable MySQL")
    engine = create_engine(url, pool_pre_ping=True)
    marker = uuid4().hex
    with Session(engine) as session:
        page = session.scalar(select(FacebookPage).where(FacebookPage.page_id == "e2e-page-a"))
        assert page is not None
        post = ScheduledPost(
            source="google_sheet",
            source_key=source_identity_key("google_sheet", "e2e", "M11", marker),
            spreadsheet_id="e2e",
            worksheet="M11",
            external_id=marker,
            source_timezone="UTC",
            status="SCHEDULED",
            caption="Concurrent claim",
            facebook_page_id=page.id,
            scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
        )
        session.add(post)
        session.commit()
        post_id = post.id
    try:
        barrier = Barrier(2)

        def worker():
            barrier.wait(timeout=15)
            with Session(engine) as session:
                return claim_due(session)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [
                future.result(timeout=30) for future in [pool.submit(worker) for _ in range(2)]
            ]
        assert results.count(post_id) == 1
        assert results.count(None) == 1
        with Session(engine) as session:
            persisted = session.get(ScheduledPost, post_id)
            assert persisted.status == "PUBLISHING"
            assert persisted.attempt_count == 1
    finally:
        with Session(engine) as session:
            session.execute(delete(ScheduledPost).where(ScheduledPost.id == post_id))
            session.commit()
        engine.dispose()
