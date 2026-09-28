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
    upsert_message,
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
            # Resolve CustomerIdentity before racing message insertions.
            # Full webhook processing refreshes its last_seen_at and flushes
            # the identity row before upsert_message; that row lock correctly
            # serializes deliveries for this PSID, so a barrier at Message.add
            # in the full flow deadlocks the test, not the production service.
            page = session.scalar(select(FacebookPage).where(FacebookPage.page_id == "e2e-page-a"))
            assert page is not None
            conversation = upsert_conversation(session, page, psid, None)
            session.commit()
            conversation_id = conversation.id

        barrier = Barrier(2)
        insert_attempts = []

        class RacingSession(Session):
            def add(self, instance, _warn=True):
                # Both sessions have passed the no-mid lookup before either
                # inserts. The unique constraint must arbitrate the collision.
                if isinstance(instance, Message) and instance.mid == mid:
                    insert_attempts.append(instance.mid)
                    barrier.wait(timeout=15)
                return super().add(instance, _warn=_warn)

        event = RawMessageEvent("e2e-page-a", psid, mid, "message", False, "hello", None, None)

        def deliver() -> bool:
            with RacingSession(engine) as session:
                thread = session.get(Conversation, conversation_id)
                assert thread is not None
                message, created = upsert_message(session, thread, event)
                session.commit()  # the loser must still have a usable transaction
                session.refresh(message)
                return created

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(deliver) for _ in range(2)]
            assert sorted(f.result(timeout=30) for f in results) == [False, True]
        assert len(insert_attempts) == 2
        with Session(engine) as session:
            assert len(session.scalars(select(Message).where(Message.mid == mid)).all()) == 1

        # Exercise the full webhook transaction too. Its identity profile
        # update may serialize the two deliveries before MID insertion, but
        # both must commit safely and only one may report a new Message.
        delivery_mid = f"m3-{uuid4().hex}"
        full_event = RawMessageEvent(
            "e2e-page-a", psid, delivery_mid, "message", False, "hello", None, None
        )
        start = Barrier(2)

        def receive() -> bool:
            with Session(engine) as session:
                start.wait(timeout=15)
                return process_webhook_events(session, [full_event])[0][2]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(receive) for _ in range(2)]
            assert sorted(f.result(timeout=30) for f in futures) == [False, True]
        with Session(engine) as session:
            committed = session.scalars(select(Message).where(Message.mid == delivery_mid)).all()
            assert len(committed) == 1
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
