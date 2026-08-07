"""Authentication business logic."""

from app.models.auth import User
from app.utils.jwt import create_access_token, create_refresh_token
from app.utils.password import verify_password
from sqlalchemy import or_, select
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


def create_token_pair(user: User) -> tuple[str, str]:
    """Issue an access/refresh pair for a user."""
    subject = str(user.uuid)
    return create_access_token(subject), create_refresh_token(subject)
