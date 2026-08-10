"""Facebook authentication and Page management endpoints."""

from __future__ import annotations

from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.models.facebook import FacebookPage
from app.schemas.facebook import (
    CurrentFacebookPageResponse,
    FacebookAuthUrlResponse,
    FacebookPageListResponse,
    FacebookPageResponse,
)
from app.services.facebook.auth import (
    exchange_code_for_token,
    generate_authorization_url,
    get_facebook_user_info,
    validate_oauth_state,
)
from app.services.facebook.exceptions import (
    FacebookApiError,
    FacebookConfigurationError,
    FacebookIntegrationError,
    FacebookOAuthStateError,
    FacebookPageUnavailableError,
)
from app.services.facebook.pages import (
    get_active_account_for_user,
    get_current_page,
    list_pages_for_user,
    select_current_page,
    sync_facebook_pages,
    upsert_facebook_account,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook", tags=["facebook"])


def serialize_page(page: FacebookPage) -> FacebookPageResponse:
    return FacebookPageResponse(
        id=str(page.uuid),
        page_id=page.page_id,
        name=page.name,
        username=page.username,
        picture_url=page.picture_url,
        is_active=page.is_active,
    )


def http_error(exc: FacebookIntegrationError) -> HTTPException:
    if isinstance(exc, FacebookConfigurationError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, FacebookOAuthStateError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, FacebookPageUnavailableError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, FacebookApiError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/auth/url", response_model=FacebookAuthUrlResponse)
def facebook_auth_url(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> FacebookAuthUrlResponse:
    try:
        return FacebookAuthUrlResponse(url=generate_authorization_url(session, current_user))
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc


@router.get("/auth/callback")
def facebook_auth_callback(
    session: Annotated[Session, Depends(get_db_session)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    from app.core.config import get_settings

    settings = get_settings()
    if error:
        return RedirectResponse(f"{settings.facebook_desktop_redirect_uri}?facebook=cancelled")
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Facebook OAuth callback data")

    try:
        user = validate_oauth_state(session, state)
        token = exchange_code_for_token(code)
        facebook_user = get_facebook_user_info(token.access_token)
        account = upsert_facebook_account(session, user, facebook_user, token)
        sync_facebook_pages(session, account)
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    return RedirectResponse(f"{settings.facebook_desktop_redirect_uri}?facebook=connected")


@router.post("/pages/sync", response_model=FacebookPageListResponse)
def sync_pages(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> FacebookPageListResponse:
    account = get_active_account_for_user(session, current_user)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook account is not connected")
    try:
        pages = sync_facebook_pages(session, account)
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc
    return FacebookPageListResponse(items=[serialize_page(page) for page in pages])


@router.get("/pages", response_model=FacebookPageListResponse)
def list_pages(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> FacebookPageListResponse:
    pages = list_pages_for_user(session, current_user)
    return FacebookPageListResponse(items=[serialize_page(page) for page in pages])


@router.get("/pages/current", response_model=CurrentFacebookPageResponse)
def current_page(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CurrentFacebookPageResponse:
    page = get_current_page(session, current_user)
    return CurrentFacebookPageResponse(item=serialize_page(page) if page else None)


@router.post("/pages/{page_id}/select", response_model=CurrentFacebookPageResponse)
def select_page(
    page_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CurrentFacebookPageResponse:
    try:
        page = select_current_page(session, current_user, page_id)
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc
    return CurrentFacebookPageResponse(item=serialize_page(page))
