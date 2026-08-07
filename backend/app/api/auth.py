"""Authentication HTTP endpoints."""
# ruff: noqa: B008

from uuid import UUID

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserResponse
from app.services.auth import authenticate_user, create_token_pair
from app.utils.jwt import create_access_token, create_refresh_token, decode_access_token
from fastapi import APIRouter, Depends, HTTPException, status
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

router = APIRouter(prefix="/auth", tags=["authentication"])
invalid_credentials = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect username or password",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db_session)) -> TokenResponse:
    user = authenticate_user(session, payload.username, payload.password)
    if user is None:
        raise invalid_credentials
    access_token, refresh_token = create_token_pair(user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, session: Session = Depends(get_db_session)) -> TokenResponse:
    try:
        claims = decode_access_token(payload.refresh_token)
        if claims.get("type") != "refresh":
            raise invalid_credentials
        user_uuid = UUID(claims["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise invalid_credentials from None
    user = session.query(User).filter(User.uuid == user_uuid, User.deleted_at.is_(None)).first()
    if user is None or not user.is_active:
        raise invalid_credentials
    return TokenResponse(
        access_token=create_access_token(str(user.uuid)),
        refresh_token=create_refresh_token(str(user.uuid)),
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(require_active_user)) -> User:
    return current_user
