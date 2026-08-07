"""FastAPI dependencies for bearer-token authentication."""
# ruff: noqa: B008

from uuid import UUID

from app.db.session import get_db_session
from app.models.auth import User
from app.utils.jwt import decode_access_token
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

bearer_scheme = HTTPBearer(auto_error=False)
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
) -> User:
    """Resolve a valid access-token bearer to its user."""
    if credentials is None:
        raise credentials_exception
    try:
        payload = decode_access_token(credentials.credentials)
        if payload.get("type") != "access":
            raise credentials_exception
        user_uuid = UUID(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise credentials_exception from None
    user = session.query(User).filter(User.uuid == user_uuid, User.deleted_at.is_(None)).first()
    if user is None:
        raise credentials_exception
    return user


def require_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Require the authenticated account to remain active."""
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return current_user
