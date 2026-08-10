"""Facebook OAuth service functions."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from app.core.config import get_settings
from app.models.auth import User
from app.models.facebook import FacebookOAuthState
from sqlalchemy.orm import Session

from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.exceptions import FacebookConfigurationError, FacebookOAuthStateError

FACEBOOK_AUTH_SCOPES = ("public_profile", "pages_show_list", "pages_read_engagement")


@dataclass(frozen=True)
class FacebookToken:
    access_token: str
    expires_at: datetime | None


@dataclass(frozen=True)
class FacebookUserInfo:
    facebook_user_id: str
    name: str | None = None


def hash_oauth_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def create_oauth_state(session: Session, user: User, expires_in_minutes: int = 10) -> str:
    state = secrets.token_urlsafe(48)
    session.add(
        FacebookOAuthState(
            user_id=user.id,
            state_hash=hash_oauth_state(state),
            expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        )
    )
    session.commit()
    return state


def validate_oauth_state(session: Session, state: str) -> User:
    stored_state = (
        session.query(FacebookOAuthState)
        .filter(FacebookOAuthState.state_hash == hash_oauth_state(state))
        .first()
    )
    now = datetime.now(UTC).replace(tzinfo=None)

    if stored_state is None or stored_state.used_at is not None or stored_state.expires_at <= now:
        raise FacebookOAuthStateError("Invalid or expired Facebook OAuth state")

    user = session.query(User).filter(User.id == stored_state.user_id, User.deleted_at.is_(None)).first()
    if user is None or not user.is_active:
        raise FacebookOAuthStateError("Facebook OAuth state is not associated with an active user")

    stored_state.used_at = now
    session.commit()
    return user


def generate_authorization_url(session: Session, user: User) -> str:
    settings = get_settings()
    if not settings.facebook_app_id or not settings.facebook_redirect_uri:
        raise FacebookConfigurationError("Facebook OAuth is not configured")

    state = create_oauth_state(session, user)
    query = urlencode(
        {
            "client_id": settings.facebook_app_id,
            "redirect_uri": settings.facebook_redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": ",".join(FACEBOOK_AUTH_SCOPES),
        }
    )
    return f"https://www.facebook.com/{settings.facebook_api_version}/dialog/oauth?{query}"


def exchange_code_for_token(code: str, client: FacebookGraphClient | None = None) -> FacebookToken:
    settings = get_settings()
    if not settings.facebook_app_id or not settings.facebook_app_secret:
        raise FacebookConfigurationError("Facebook OAuth is not configured")

    graph = client or FacebookGraphClient()
    payload = graph.get(
        "/oauth/access_token",
        {
            "client_id": settings.facebook_app_id,
            "client_secret": settings.facebook_app_secret,
            "redirect_uri": settings.facebook_redirect_uri,
            "code": code,
        },
    )
    access_token = str(payload["access_token"])
    expires_in = int(payload["expires_in"]) if payload.get("expires_in") is not None else None
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in) if expires_in else None
    return FacebookToken(access_token=access_token, expires_at=expires_at)


def get_facebook_user_info(access_token: str, client: FacebookGraphClient | None = None) -> FacebookUserInfo:
    graph = client or FacebookGraphClient()
    payload = graph.get("/me", {"fields": "id,name"}, access_token=access_token)
    return FacebookUserInfo(facebook_user_id=str(payload["id"]), name=payload.get("name"))
