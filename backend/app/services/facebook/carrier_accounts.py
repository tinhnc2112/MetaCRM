"""Page-scoped carrier account services."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.carriers.base import CarrierProvider
from app.carriers.registry import carrier_registry
from app.models.auth import User
from app.models.carriers import CarrierAccount
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.pages import get_current_page
from sqlalchemy.orm import Session


class CarrierProviderUnavailableError(ValueError):
    pass


class CarrierAccountStateError(ValueError):
    pass


_SECRET_KEY_FRAGMENTS = (
    "credential",
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
)


def _validate_non_secret_configuration(configuration: Mapping[str, object]) -> None:
    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, nested_value in value.items():
                normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
                if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                    raise ValueError("configuration cannot contain credentials or secrets")
                visit(nested_value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(configuration)


def list_carrier_providers() -> tuple[CarrierProvider, ...]:
    return carrier_registry.list()


def _provider(code: str) -> CarrierProvider:
    provider = carrier_registry.get(code)
    if provider is None:
        raise CarrierProviderUnavailableError("Carrier provider is not available")
    return provider


def _encrypt_credentials(credentials: Mapping[str, object], cipher: TokenCipher | None = None) -> str | None:
    if not credentials:
        return None
    serialized = json.dumps(credentials, separators=(",", ":"), sort_keys=True)
    return (cipher or TokenCipher()).encrypt(serialized)


def _resolve_account_for_page(
    session: Session,
    user: User,
    account_uuid: str,
    *,
    lock: bool = False,
) -> CarrierAccount | None:
    try:
        public_id = UUID(account_uuid)
    except ValueError:
        return None
    page = get_current_page(session, user)
    if page is None:
        return None
    query = session.query(CarrierAccount).filter(
        CarrierAccount.public_id == public_id,
        CarrierAccount.facebook_page_id == page.id,
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def list_carrier_accounts(session: Session, user: User) -> list[CarrierAccount]:
    page = get_current_page(session, user)
    if page is None:
        return []
    return (
        session.query(CarrierAccount)
        .filter(CarrierAccount.facebook_page_id == page.id)
        .order_by(CarrierAccount.created_at.desc(), CarrierAccount.id.desc())
        .all()
    )


def get_carrier_account(session: Session, user: User, account_uuid: str) -> CarrierAccount | None:
    return _resolve_account_for_page(session, user, account_uuid)


def create_carrier_account(
    session: Session,
    user: User,
    *,
    provider_code: str,
    display_name: str,
    credentials: Mapping[str, object] | None,
    configuration: Mapping[str, object],
) -> CarrierAccount | None:
    provider = _provider(provider_code)
    _validate_non_secret_configuration(configuration)
    provider.validate_configuration(configuration)
    provider.validate_credentials(credentials or {})
    page = get_current_page(session, user)
    if page is None:
        return None
    now = datetime.now(UTC)
    try:
        account = CarrierAccount(
            public_id=uuid4(),
            facebook_page_id=page.id,
            provider_code=provider.code,
            display_name=display_name,
            status="active",
            credentials_encrypted=_encrypt_credentials(credentials or {}),
            configuration=dict(configuration),
            created_by_id=user.id,
            updated_by_id=user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return account
    except Exception:
        session.rollback()
        raise


def update_carrier_account(
    session: Session,
    user: User,
    account_uuid: str,
    data: Mapping[str, object],
) -> CarrierAccount | None:
    try:
        account = _resolve_account_for_page(session, user, account_uuid, lock=True)
        if account is None:
            return None
        if account.status != "active":
            raise CarrierAccountStateError("Inactive carrier accounts cannot be updated")
        provider = _provider(account.provider_code)
        if "configuration" in data and data["configuration"] is not None:
            configuration = data["configuration"]
            if not isinstance(configuration, Mapping):
                raise ValueError("configuration must be an object")
            _validate_non_secret_configuration(configuration)
            provider.validate_configuration(configuration)
            account.configuration = dict(configuration)
        if "display_name" in data and data["display_name"] is not None:
            account.display_name = str(data["display_name"])
        account.updated_by_id = user.id
        account.updated_at = datetime.now(UTC)
        session.add(account)
        session.commit()
        session.refresh(account)
        return account
    except Exception:
        session.rollback()
        raise


def replace_carrier_credentials(
    session: Session,
    user: User,
    account_uuid: str,
    credentials: Mapping[str, object],
) -> CarrierAccount | None:
    try:
        account = _resolve_account_for_page(session, user, account_uuid, lock=True)
        if account is None:
            return None
        if account.status != "active":
            raise CarrierAccountStateError("Inactive carrier accounts cannot be updated")
        provider = _provider(account.provider_code)
        if not provider.capabilities.supports_credentials:
            raise ValueError(f"{provider.display_name} carrier accounts do not accept credentials")
        provider.validate_credentials(credentials)
        account.credentials_encrypted = _encrypt_credentials(credentials)
        account.updated_by_id = user.id
        account.updated_at = datetime.now(UTC)
        session.add(account)
        session.commit()
        session.refresh(account)
        return account
    except Exception:
        session.rollback()
        raise


def deactivate_carrier_account(
    session: Session,
    user: User,
    account_uuid: str,
) -> CarrierAccount | None:
    try:
        account = _resolve_account_for_page(session, user, account_uuid, lock=True)
        if account is None:
            return None
        if account.status == "inactive":
            return account
        now = datetime.now(UTC)
        account.status = "inactive"
        account.credentials_encrypted = None
        account.updated_by_id = user.id
        account.updated_at = now
        account.deactivated_by_id = user.id
        account.deactivated_at = now
        session.add(account)
        session.commit()
        session.refresh(account)
        return account
    except Exception:
        session.rollback()
        raise
