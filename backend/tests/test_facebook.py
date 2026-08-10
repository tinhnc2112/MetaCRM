from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import User
from app.models.facebook import FacebookAccount, FacebookPage
from app.services.facebook.auth import create_oauth_state, validate_oauth_state
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import FacebookOAuthStateError
from app.services.facebook.pages import FacebookPageData, sync_facebook_pages
from app.utils.jwt import create_access_token
from app.utils.password import hash_password
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_TOKEN_KEY = "test-facebook-token-encryption-key"


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session]:
    monkeypatch.setenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", TEST_TOKEN_KEY)
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    database_session = local_session()
    database_session.add_all(
        [
            User(
                username="alice",
                email="alice@example.com",
                password_hash=hash_password("correct-password"),
                full_name="Alice Example",
            ),
            User(
                username="bob",
                email="bob@example.com",
                password_hash=hash_password("correct-password"),
                full_name="Bob Example",
            ),
        ]
    )
    database_session.commit()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()
        get_settings.cache_clear()


@pytest.fixture()
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr("app.startup.lifecycle.init_db", lambda: None)

    def override_db() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.uuid))}"}


def create_account_with_pages(session: Session, user: User, page_id: str = "page-1") -> FacebookPage:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id=f"fb-{user.username}",
        access_token_encrypted=cipher.encrypt("user-access-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(account)
    session.commit()
    page = FacebookPage(
        facebook_account_id=account.id,
        page_id=page_id,
        name=f"{user.username} Page",
        username=f"{user.username}-page",
        picture_url="https://example.com/page.png",
        access_token_encrypted=cipher.encrypt("page-access-token"),
        is_active=True,
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    return page


def test_oauth_state_generation_and_single_use_validation(session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    state = create_oauth_state(session, user)

    assert state
    assert validate_oauth_state(session, state).id == user.id

    with pytest.raises(FacebookOAuthStateError):
        validate_oauth_state(session, state)


def test_token_encryption_round_trip() -> None:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    encrypted = cipher.encrypt("facebook-access-token")

    assert encrypted != "facebook-access-token"
    assert cipher.decrypt(encrypted) == "facebook-access-token"


def test_facebook_account_creation_and_page_sync(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    cipher = TokenCipher(TEST_TOKEN_KEY)
    account = FacebookAccount(
        user_id=user.id,
        facebook_user_id="fb-user-1",
        access_token_encrypted=cipher.encrypt("user-token"),
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(account)
    session.commit()

    monkeypatch.setattr(
        "app.services.facebook.pages.retrieve_available_pages",
        lambda access_token, client=None: [
            FacebookPageData(
                page_id="page-1",
                name="Page One",
                username="pageone",
                picture_url="https://example.com/p.png",
                access_token="page-token",
            )
        ],
    )

    pages = sync_facebook_pages(session, account, cipher=cipher)

    assert len(pages) == 1
    assert pages[0].page_id == "page-1"
    assert pages[0].access_token_encrypted != "page-token"
    assert cipher.decrypt(pages[0].access_token_encrypted or "") == "page-token"


def test_page_listing_does_not_expose_tokens(client: TestClient, session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)

    response = client.get("/api/v1/facebook/pages", headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["page_id"] == "page-1"
    assert "access_token" not in str(body)
    assert "page-access-token" not in str(body)


def test_page_selection_and_current_page(client: TestClient, session: Session) -> None:
    user = session.query(User).filter(User.username == "alice").one()
    create_account_with_pages(session, user)

    selected = client.post("/api/v1/facebook/pages/page-1/select", headers=auth_headers(user))
    current = client.get("/api/v1/facebook/pages/current", headers=auth_headers(user))

    assert selected.status_code == 200
    assert selected.json()["item"]["page_id"] == "page-1"
    assert current.status_code == 200
    assert current.json()["item"]["page_id"] == "page-1"


def test_user_cannot_select_another_users_page(client: TestClient, session: Session) -> None:
    alice = session.query(User).filter(User.username == "alice").one()
    bob = session.query(User).filter(User.username == "bob").one()
    create_account_with_pages(session, bob, page_id="bob-page")

    response = client.post("/api/v1/facebook/pages/bob-page/select", headers=auth_headers(alice))

    assert response.status_code == 404
