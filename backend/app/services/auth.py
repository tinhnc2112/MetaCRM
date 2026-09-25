"""Authentication and durable refresh credential lifecycle."""

from datetime import UTC, datetime
from uuid import UUID

from app.models.auth import RefreshSession, User
from app.utils.jwt import create_access_token, create_refresh_token, decode_access_token
from app.utils.password import verify_password
from jwt.exceptions import InvalidTokenError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session


def authenticate_user(session: Session, login: str, password: str) -> User | None:
    """Return an active, non-deleted user when credentials are valid."""
    user = session.scalar(
        select(User).where(
            User.deleted_at.is_(None), or_(User.username == login, User.email == login)
        )
    )
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def create_token_pair(session: Session, user: User) -> tuple[str, str]:
    """Issue and commit a refresh credential before exposing the token pair."""
    subject = str(user.uuid)
    access_token = create_access_token(subject)
    refresh_token = create_refresh_token(subject)
    claims = decode_access_token(refresh_token)
    session.add(
        RefreshSession(
            user_id=user.id,
            token_id=claims["jti"],
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return access_token, refresh_token


def _active_refresh_user(session: Session, token: str) -> tuple[User, str] | None:
    try:
        claims = decode_access_token(token)
        if claims.get("type") != "refresh" or not claims.get("jti"):
            return None
        UUID(claims["jti"])
        user_uuid = UUID(claims["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        return None
    user = session.scalar(
        select(User).where(User.uuid == user_uuid, User.is_active.is_(True),
                           User.deleted_at.is_(None)).with_for_update()
    )
    return (user, claims["jti"]) if user is not None else None


def rotate_refresh_token(session: Session, token: str) -> tuple[str, str] | None:
    """Single conditional DB transition owns both consumption and replacement."""
    identity = _active_refresh_user(session, token)
    if identity is None:
        return None
    user, token_id = identity
    now = datetime.now(UTC)
    result = session.execute(
        update(RefreshSession).where(
            RefreshSession.token_id == token_id,
            RefreshSession.user_id == user.id,
            RefreshSession.consumed_at.is_(None),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
        ).values(consumed_at=now)
    )
    if result.rowcount != 1:
        session.rollback()
        return None

    replacement = create_refresh_token(str(user.uuid))
    claims = decode_access_token(replacement)
    session.add(RefreshSession(
        user_id=user.id,
        token_id=claims["jti"],
        expires_at=datetime.fromtimestamp(claims["exp"], UTC),
    ))
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return create_access_token(str(user.uuid)), replacement


def revoke_refresh_token(session: Session, token: str) -> bool:
    identity = _active_refresh_user(session, token)
    if identity is None:
        return False
    user, token_id = identity
    result = session.execute(
        update(RefreshSession).where(
            RefreshSession.token_id == token_id,
            RefreshSession.user_id == user.id,
            RefreshSession.consumed_at.is_(None),
            RefreshSession.revoked_at.is_(None),
        ).values(revoked_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        session.rollback()
        return False
    session.commit()
    return True
