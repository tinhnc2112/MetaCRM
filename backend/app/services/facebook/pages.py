"""Facebook account and Page synchronization services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.auth import User
from app.models.facebook import FacebookAccount, FacebookPage, UserPageContext
from sqlalchemy.orm import Session

from app.services.facebook.auth import FacebookToken, FacebookUserInfo
from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import FacebookPageUnavailableError


@dataclass(frozen=True)
class FacebookPageData:
    page_id: str
    name: str
    username: str | None
    picture_url: str | None
    access_token: str | None


def upsert_facebook_account(
    session: Session,
    user: User,
    facebook_user: FacebookUserInfo,
    token: FacebookToken,
    cipher: TokenCipher | None = None,
) -> FacebookAccount:
    token_cipher = cipher or TokenCipher()
    account = (
        session.query(FacebookAccount)
        .filter(FacebookAccount.facebook_user_id == facebook_user.facebook_user_id)
        .first()
    )
    if account is None:
        account = FacebookAccount(user_id=user.id, facebook_user_id=facebook_user.facebook_user_id)
        session.add(account)

    account.user_id = user.id
    account.access_token_encrypted = token_cipher.encrypt(token.access_token)
    account.token_expires_at = token.expires_at
    account.is_active = True
    account.deleted_at = None
    session.commit()
    session.refresh(account)
    return account


def retrieve_available_pages(
    access_token: str,
    client: FacebookGraphClient | None = None,
) -> list[FacebookPageData]:
    graph = client or FacebookGraphClient()
    payload = graph.get(
        "/me/accounts",
        {
            "fields": "id,name,username,picture{url},access_token",
        },
        access_token=access_token,
    )
    pages: list[FacebookPageData] = []
    for item in payload.get("data", []):
        picture = item.get("picture", {})
        picture_data = picture.get("data", {}) if isinstance(picture, dict) else {}
        pages.append(
            FacebookPageData(
                page_id=str(item["id"]),
                name=str(item["name"]),
                username=item.get("username"),
                picture_url=picture_data.get("url"),
                access_token=item.get("access_token"),
            )
        )
    return pages


def sync_facebook_pages(
    session: Session,
    account: FacebookAccount,
    client: FacebookGraphClient | None = None,
    cipher: TokenCipher | None = None,
) -> list[FacebookPage]:
    token_cipher = cipher or TokenCipher()
    user_access_token = token_cipher.decrypt(account.access_token_encrypted)
    pages = retrieve_available_pages(user_access_token, client=client)
    synced_pages: list[FacebookPage] = []
    now = datetime.now(UTC)

    for page_data in pages:
        page = session.query(FacebookPage).filter(FacebookPage.page_id == page_data.page_id).first()
        encrypted_page_token = (
            token_cipher.encrypt(page_data.access_token) if page_data.access_token else None
        )

        if page is None:
            page = FacebookPage(
                facebook_account_id=account.id,
                page_id=page_data.page_id,
                name=page_data.name,
            )
            session.add(page)

        page.facebook_account_id = account.id
        page.name = page_data.name
        page.username = page_data.username
        page.picture_url = page_data.picture_url
        page.access_token_encrypted = encrypted_page_token
        page.token_expires_at = account.token_expires_at
        page.is_active = True
        page.deleted_at = None
        page.last_synced_at = now
        synced_pages.append(page)

    session.commit()
    for page in synced_pages:
        session.refresh(page)
    return synced_pages


def get_active_account_for_user(session: Session, user: User) -> FacebookAccount | None:
    return (
        session.query(FacebookAccount)
        .filter(
            FacebookAccount.user_id == user.id,
            FacebookAccount.is_active.is_(True),
            FacebookAccount.deleted_at.is_(None),
        )
        .order_by(FacebookAccount.created_at.desc())
        .first()
    )


def list_pages_for_user(session: Session, user: User) -> list[FacebookPage]:
    return (
        session.query(FacebookPage)
        .join(FacebookAccount, FacebookAccount.id == FacebookPage.facebook_account_id)
        .filter(
            FacebookAccount.user_id == user.id,
            FacebookAccount.is_active.is_(True),
            FacebookAccount.deleted_at.is_(None),
            FacebookPage.deleted_at.is_(None),
        )
        .order_by(FacebookPage.name.asc())
        .all()
    )


def get_page_for_user(session: Session, user: User, page_id: str) -> FacebookPage:
    page = (
        session.query(FacebookPage)
        .join(FacebookAccount, FacebookAccount.id == FacebookPage.facebook_account_id)
        .filter(
            FacebookAccount.user_id == user.id,
            FacebookPage.page_id == page_id,
            FacebookPage.deleted_at.is_(None),
        )
        .first()
    )
    if page is None:
        raise FacebookPageUnavailableError("Facebook Page is not available for this user")
    return page


def select_current_page(session: Session, user: User, page_id: str) -> FacebookPage:
    page = get_page_for_user(session, user, page_id)
    context = session.query(UserPageContext).filter(UserPageContext.user_id == user.id).first()
    if context is None:
        context = UserPageContext(user_id=user.id, facebook_page_id=page.id)
        session.add(context)
    else:
        context.facebook_page_id = page.id
    session.commit()
    session.refresh(page)
    return page


def get_current_page(session: Session, user: User) -> FacebookPage | None:
    context = session.query(UserPageContext).filter(UserPageContext.user_id == user.id).first()
    if context is None:
        return None
    return (
        session.query(FacebookPage)
        .join(FacebookAccount, FacebookAccount.id == FacebookPage.facebook_account_id)
        .filter(
            FacebookPage.id == context.facebook_page_id,
            FacebookAccount.user_id == user.id,
            FacebookPage.deleted_at.is_(None),
        )
        .first()
    )
