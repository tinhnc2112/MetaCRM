"""InnoDB proof that two deliveries racing on the same mid have one winner."""

from concurrent.futures import ThreadPoolExecutor
from os import environ
from threading import Barrier
from uuid import uuid4

import pytest
from app.models.customer_core import Customer, CustomerIdentity
from app.models.facebook import FacebookPage
from app.models.messenger import Conversation, Message
from app.services.facebook.messenger import (
    RawMessageEvent,
    process_webhook_events,
    upsert_conversation,
)
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def test_mysql_parallel_duplicate_mid_has_one_committed_winner() -> None:
    url = environ.get("DATABASE_URL", "")
    try:
        target = make_url(url)
    except Exception:
        pytest.skip("requires guarded disposable MySQL test database")
    if (
        environ.get("APP_ENV") != "test"
        or environ.get("METACRM_E2E") != "true"
        or target.drivername != "mysql+pymysql"
        or target.database != "metacrm_m0_test_e2e"
        or target.host not in {"localhost", "127.0.0.1"}
    ):
        pytest.skip("requires guarded disposable MySQL test database")

    engine = create_engine(url, pool_pre_ping=True)
    psid, mid = f"m3-{uuid4().hex}", f"m3-{uuid4().hex}"
    try:
        with Session(engine) as session:
            # Precreate the thread to isolate the mid collision from the
            # separate conversation/customer identity insertion race.
            page = session.scalar(select(FacebookPage).where(FacebookPage.page_id == "e2e-page-a"))
            assert page is not None
            upsert_conversation(session, page, psid, None)
            session.commit()

        barrier = Barrier(2)
        class RacingSession(Session):
            def add(self, instance, _warn=True):
                # Both deliveries have already observed no mid before either
                # may INSERT. This actually exercises the unique-key loser.
                if isinstance(instance, Message) and instance.mid == mid:
                    barrier.wait(timeout=15)
                return super().add(instance, _warn=_warn)

        event = RawMessageEvent("e2e-page-a", psid, mid, "message", False, "hello", None, None)

        def deliver() -> bool:
            with RacingSession(engine) as session:
                result = process_webhook_events(session, [event])
                return result[0][2]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(deliver) for _ in range(2)]
            assert sorted(f.result(timeout=30) for f in results) == [False, True]
        with Session(engine) as session:
            assert session.scalar(select(Message).where(Message.mid == mid)) is not None
            assert len(session.scalars(select(Message).where(Message.mid == mid)).all()) == 1
    finally:
        with Session(engine) as session:
            conversations = session.scalars(
                select(Conversation).where(Conversation.psid == psid)
            ).all()
            for conversation in conversations:
                session.execute(delete(Message).where(Message.conversation_id == conversation.id))
                session.delete(conversation)
                session.flush()
                identities = session.scalars(
                    select(CustomerIdentity).where(
                        CustomerIdentity.facebook_page_id == conversation.facebook_page_id,
                        CustomerIdentity.external_id == psid,
                    )
                ).all()
                for identity in identities:
                    customer_id = identity.customer_id
                    session.delete(identity)
                    session.flush()
                    session.execute(delete(Customer).where(Customer.id == customer_id))
            session.commit()
        engine.dispose()
