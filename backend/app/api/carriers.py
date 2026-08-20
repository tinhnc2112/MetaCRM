"""Carrier provider and Page-scoped account endpoints."""

from __future__ import annotations

from typing import Annotated

from app.db.session import get_db_session
from app.dependencies.auth import require_active_user
from app.models.auth import User
from app.schemas.carriers import (
    CarrierAccountCreate,
    CarrierAccountListResponse,
    CarrierAccountResponse,
    CarrierAccountUpdate,
    CarrierCapabilitiesResponse,
    CarrierCredentialsUpdate,
    CarrierProviderListResponse,
    CarrierProviderResponse,
)
from app.services.facebook.carrier_accounts import (
    CarrierAccountStateError,
    CarrierProviderUnavailableError,
    create_carrier_account,
    deactivate_carrier_account,
    get_carrier_account,
    list_carrier_accounts,
    list_carrier_providers,
    replace_carrier_credentials,
    update_carrier_account,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook", tags=["carriers"])


def _account_response(account) -> CarrierAccountResponse:
    return CarrierAccountResponse(
        uuid=str(account.public_id),
        provider_code=account.provider_code,
        display_name=account.display_name,
        status=account.status,
        configuration=account.configuration or {},
        configured=account.configured,
        created_at=account.created_at,
        updated_at=account.updated_at,
        deactivated_at=account.deactivated_at,
    )


def _account_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CarrierProviderUnavailableError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, CarrierAccountStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/carriers/providers", response_model=CarrierProviderListResponse)
def list_carrier_providers_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
) -> CarrierProviderListResponse:
    del current_user
    return CarrierProviderListResponse(
        items=[
            CarrierProviderResponse(
                code=provider.code,
                display_name=provider.display_name,
                capabilities=CarrierCapabilitiesResponse(**vars(provider.capabilities)),
            )
            for provider in list_carrier_providers()
        ]
    )


@router.get("/carrier-accounts", response_model=CarrierAccountListResponse)
def list_carrier_accounts_endpoint(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CarrierAccountListResponse:
    return CarrierAccountListResponse(
        items=[_account_response(account) for account in list_carrier_accounts(session, current_user)]
    )


@router.post(
    "/carrier-accounts",
    response_model=CarrierAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_carrier_account_endpoint(
    payload: CarrierAccountCreate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CarrierAccountResponse:
    try:
        account = create_carrier_account(
            session,
            current_user,
            provider_code=payload.provider_code,
            display_name=payload.display_name,
            credentials=payload.credentials,
            configuration=payload.configuration,
        )
    except (CarrierProviderUnavailableError, ValueError) as exc:
        raise _account_error(exc) from exc
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook Page not found")
    return _account_response(account)


@router.get("/carrier-accounts/{account_uuid}", response_model=CarrierAccountResponse)
def get_carrier_account_endpoint(
    account_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CarrierAccountResponse:
    account = get_carrier_account(session, current_user, account_uuid)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier account not found")
    return _account_response(account)


@router.patch("/carrier-accounts/{account_uuid}", response_model=CarrierAccountResponse)
def update_carrier_account_endpoint(
    account_uuid: str,
    payload: CarrierAccountUpdate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CarrierAccountResponse:
    try:
        account = update_carrier_account(
            session, current_user, account_uuid, payload.model_dump(exclude_unset=True)
        )
    except (CarrierProviderUnavailableError, CarrierAccountStateError, ValueError) as exc:
        raise _account_error(exc) from exc
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier account not found")
    return _account_response(account)


@router.put("/carrier-accounts/{account_uuid}/credentials", response_model=CarrierAccountResponse)
def replace_carrier_credentials_endpoint(
    account_uuid: str,
    payload: CarrierCredentialsUpdate,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CarrierAccountResponse:
    try:
        account = replace_carrier_credentials(
            session, current_user, account_uuid, payload.credentials
        )
    except (CarrierProviderUnavailableError, CarrierAccountStateError, ValueError) as exc:
        raise _account_error(exc) from exc
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier account not found")
    return _account_response(account)


@router.post("/carrier-accounts/{account_uuid}/deactivate", response_model=CarrierAccountResponse)
def deactivate_carrier_account_endpoint(
    account_uuid: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CarrierAccountResponse:
    account = deactivate_carrier_account(session, current_user, account_uuid)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier account not found")
    return _account_response(account)
