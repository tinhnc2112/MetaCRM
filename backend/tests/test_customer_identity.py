"""Page-scoped CustomerIdentity runtime and migration regression tests."""

from __future__ import annotations

import importlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from app.db.base import Base
from app.models.auth import User
from app.models.customer_core import Customer, CustomerIdentity
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.messenger import Conversation
from app.services import customer_identity as identity_service
from app.services.customer_identity import (
    CHANNEL_FACEBOOK,
    CustomerIdentityConsistencyError,
    backfill_conversation_customers,
    get_or_create_customer_identity,
    resolve_customer_for_conversation,
)
from app.services.facebook import messenger as messenger_service
from app.services.facebook.crypto import TokenCipher
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

migration_0016 = importlib.import_module("migrations.versions.0016_customer_identity_page_scope")
TEST_TOKEN_KEY = "test-customer-identity-page-scope-key"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield database
    finally:
        database.close()
        engine.dispose()


def _make_page(session: Session, *, username: str, page_id: str) -> FacebookPage:
    user = session.query(User).filter(User.username == username).first()
    if user is None:
        user = User(username=username, email=f"{username}@example.com", password_hash="hashed")
        session.add(user)
        session.flush()
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id=f"fb-{username}-{page_id}",
        access_token_encrypted=cipher.encrypt("token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(account)
    session.flush()
    page = FacebookPage(
        facebook_account_id=account.id,
        page_id=page_id,
        name=page_id,
        is_active=True,
    )
    session.add(page)
    session.commit()
    return page


def _make_conversation(
    session: Session,
    page: FacebookPage,
    psid: str,
    *,
    customer_id: int | None = None,
) -> Conversation:
    conversation = Conversation(
        facebook_page_id=page.id,
        page_id=page.page_id,
        psid=psid,
        customer_id=customer_id,
    )
    session.add(conversation)
    session.flush()
    return conversation


def test_same_page_and_psid_reuses_identity_and_customer(session: Session) -> None:
    page = _make_page(session, username="alice", page_id="page-a")
    first = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=page.id,
        external_id="same-psid",
    )
    second = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=page.id,
        external_id="same-psid",
    )
    assert second.id == first.id
    assert second.customer_id == first.customer_id
    assert session.query(CustomerIdentity).count() == 1
    assert session.query(Customer).count() == 1


def test_different_pages_with_same_psid_are_isolated(session: Session) -> None:
    page_a = _make_page(session, username="alice", page_id="page-a")
    page_b = _make_page(session, username="alice", page_id="page-b")
    first = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=page_a.id,
        external_id="shared-number",
    )
    second = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=page_b.id,
        external_id="shared-number",
    )
    assert first.id != second.id
    assert first.customer_id != second.customer_id


def test_different_users_with_same_psid_are_isolated(session: Session) -> None:
    alice_page = _make_page(session, username="alice", page_id="alice-page")
    bob_page = _make_page(session, username="bob", page_id="bob-page")
    alice_conversation = _make_conversation(session, alice_page, "equal-psid")
    bob_conversation = _make_conversation(session, bob_page, "equal-psid")
    assert resolve_customer_for_conversation(
        session, alice_conversation
    ) != resolve_customer_for_conversation(session, bob_conversation)


def test_resolver_derives_scope_from_conversation(session: Session) -> None:
    page_a = _make_page(session, username="alice", page_id="page-a")
    page_b = _make_page(session, username="alice", page_id="page-b")
    resolve_customer_for_conversation(session, _make_conversation(session, page_a, "same-psid"))
    resolve_customer_for_conversation(session, _make_conversation(session, page_b, "same-psid"))
    identities = session.query(CustomerIdentity).order_by(CustomerIdentity.facebook_page_id).all()
    assert [(row.facebook_page_id, row.external_id) for row in identities] == [
        (page_a.id, "same-psid"),
        (page_b.id, "same-psid"),
    ]


def test_backfill_conversations_resolves_each_page_independently(session: Session) -> None:
    page_a = _make_page(session, username="alice", page_id="page-a")
    page_b = _make_page(session, username="alice", page_id="page-b")
    first = _make_conversation(session, page_a, "same-psid")
    second = _make_conversation(session, page_b, "same-psid")
    result = backfill_conversation_customers(session)
    assert result.conversations_linked == 2
    assert result.customers_created == 2
    assert first.customer_id != second.customer_id


def test_merged_secondary_resolves_to_canonical_customer(session: Session) -> None:
    page = _make_page(session, username="alice", page_id="page-a")
    primary = Customer(name="Primary")
    secondary = Customer(name="Secondary")
    session.add_all([primary, secondary])
    session.flush()
    secondary.merged_into_customer_id = primary.id
    conversation = _make_conversation(session, page, "merged-psid", customer_id=secondary.id)
    identity = CustomerIdentity(
        customer_id=secondary.id,
        facebook_page_id=page.id,
        channel=CHANNEL_FACEBOOK,
        external_id="merged-psid",
    )
    session.add(identity)
    session.flush()
    assert resolve_customer_for_conversation(session, conversation) == primary.id
    assert conversation.customer_id == primary.id
    assert identity.customer_id == primary.id


def test_scoped_identity_customer_mismatch_fails_closed(session: Session) -> None:
    page = _make_page(session, username="alice", page_id="page-a")
    conversation_customer = Customer(name="Conversation owner")
    identity_customer = Customer(name="Identity owner")
    session.add_all([conversation_customer, identity_customer])
    session.flush()
    conversation = _make_conversation(
        session, page, "conflict-psid", customer_id=conversation_customer.id
    )
    session.add(
        CustomerIdentity(
            customer_id=identity_customer.id,
            facebook_page_id=page.id,
            channel=CHANNEL_FACEBOOK,
            external_id="conflict-psid",
        )
    )
    session.flush()
    with pytest.raises(CustomerIdentityConsistencyError):
        resolve_customer_for_conversation(session, conversation)
    assert conversation.customer_id == conversation_customer.id


def test_identity_unique_race_reloads_winner_without_orphan_customer(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _make_page(session, username="alice", page_id="page-a")
    winner = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=page.id,
        external_id="raced-psid",
    )
    session.commit()
    customer_count = session.query(Customer).count()
    original_find = identity_service._find_customer_identity
    calls = 0

    def stale_then_current(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original_find(*args, **kwargs)

    monkeypatch.setattr(identity_service, "_find_customer_identity", stale_then_current)
    resolved = get_or_create_customer_identity(
        session,
        channel=CHANNEL_FACEBOOK,
        facebook_page_id=page.id,
        external_id="raced-psid",
    )
    assert resolved.id == winner.id
    assert session.query(Customer).count() == customer_count


def test_conversation_unique_race_reloads_winner(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _make_page(session, username="alice", page_id="page-a")
    winner = messenger_service.upsert_conversation(session, page, "raced-psid", None)
    session.commit()
    original_find = messenger_service._find_conversation
    calls = 0

    def stale_then_current(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original_find(*args, **kwargs)

    monkeypatch.setattr(messenger_service, "_find_conversation", stale_then_current)
    resolved = messenger_service.upsert_conversation(session, page, "raced-psid", None)
    assert resolved.id == winner.id
    assert session.query(Conversation).count() == 1


def _old_identity_schema():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    customers = Table("customers", metadata, Column("id", Integer, primary_key=True))
    pages = Table("facebook_pages", metadata, Column("id", Integer, primary_key=True))
    identities = Table(
        "customer_identities",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
        Column("channel", String(32), nullable=False),
        Column("external_id", String(128), nullable=False),
    )
    conversations = Table(
        "facebook_conversations",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, ForeignKey("customers.id")),
        Column("facebook_page_id", Integer, ForeignKey("facebook_pages.id"), nullable=False),
        Column("psid", String(128), nullable=False),
    )
    metadata.create_all(engine)
    return engine, customers, pages, identities, conversations


def test_migration_backfill_infers_exactly_one_page() -> None:
    engine, customers, pages, identities, conversations = _old_identity_schema()
    with engine.begin() as connection:
        connection.execute(customers.insert().values(id=1))
        connection.execute(pages.insert().values(id=10))
        connection.execute(
            identities.insert().values(id=100, customer_id=1, channel="FACEBOOK", external_id="p")
        )
        connection.execute(
            conversations.insert().values(id=1000, customer_id=1, facebook_page_id=10, psid="p")
        )
        assert migration_0016._identity_page_assignments(connection) == {100: 10}
    engine.dispose()


def test_migration_backfill_rejects_identity_without_conversation() -> None:
    engine, customers, _pages, identities, _conversations = _old_identity_schema()
    with engine.begin() as connection:
        connection.execute(customers.insert().values(id=1))
        connection.execute(
            identities.insert().values(id=100, customer_id=1, channel="FACEBOOK", external_id="p")
        )
        with pytest.raises(RuntimeError, match="no matching Conversation"):
            migration_0016._identity_page_assignments(connection)
    engine.dispose()


def test_migration_backfill_rejects_multiple_pages() -> None:
    engine, customers, pages, identities, conversations = _old_identity_schema()
    with engine.begin() as connection:
        connection.execute(customers.insert().values(id=1))
        connection.execute(pages.insert(), [{"id": 10}, {"id": 20}])
        connection.execute(
            identities.insert().values(id=100, customer_id=1, channel="FACEBOOK", external_id="p")
        )
        connection.execute(
            conversations.insert(),
            [
                {"id": 1000, "customer_id": 1, "facebook_page_id": 10, "psid": "p"},
                {"id": 1001, "customer_id": 1, "facebook_page_id": 20, "psid": "p"},
            ],
        )
        with pytest.raises(RuntimeError, match="multiple matching Pages"):
            migration_0016._identity_page_assignments(connection)
    engine.dispose()
