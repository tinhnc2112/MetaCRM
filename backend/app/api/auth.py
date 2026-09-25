"""Authentication HTTP endpoints."""
# ruff: noqa: B008

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserResponse
from app.services.auth import (
    authenticate_user,
    create_token_pair,
    revoke_refresh_token,
    rotate_refresh_token,
)
from fastapi import APIRouter, Depends, HTTPException, status
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
    access_token, refresh_token = create_token_pair(session, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, session: Session = Depends(get_db_session)) -> TokenResponse:
    pair = rotate_refresh_token(session, payload.refresh_token)
    if pair is None:
        raise invalid_credentials
    return TokenResponse(access_token=pair[0], refresh_token=pair[1])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, session: Session = Depends(get_db_session)) -> None:
    if not revoke_refresh_token(session, payload.refresh_token):
        raise invalid_credentials


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(require_active_user)) -> User:
    return current_user
