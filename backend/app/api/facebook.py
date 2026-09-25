"""Facebook authentication and Page management endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from app.api.webhook import read_and_log_webhook_request
from app.core.config import get_settings
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
from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.crypto import TokenCipher
from app.services.facebook.exceptions import (
    FacebookApiError,
    FacebookConfigurationError,
    FacebookIntegrationError,
    FacebookOAuthStateError,
    FacebookPageUnavailableError,
    FacebookTokenError,
)
from app.services.facebook.pages import (
    get_active_account_for_user,
    get_current_page,
    get_page_for_user,
    list_pages_for_user,
    select_current_page,
    sync_facebook_pages,
    upsert_facebook_account,
)
from app.services.facebook.subscriptions import SUBSCRIBED_FIELDS
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from loguru import logger
from sqlalchemy.orm import Session

router = APIRouter(prefix="/facebook", tags=["facebook"])

MESSENGER_DIAGNOSTICS_GRAPH_VERSION = "v26.0"
REQUIRED_MESSENGER_SCOPES = {
    "pages_manage_metadata",
    "pages_messaging",
    "pages_read_engagement",
    "pages_show_list",
}
MESSENGER_PAGE_TASKS = {
    "MESSAGING",
    "MODERATE",
    "PROFILE_PLUS_FULL_CONTROL",
    "PROFILE_PLUS_MESSAGING",
    "PROFILE_PLUS_MODERATE",
}


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
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Facebook API request failed"
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def safe_graph_diagnostics(value: Any) -> Any:
    """Keep known Graph metadata; redact unexpected fields and credentials."""
    if isinstance(value, dict):
        safe_fields = {
            "data", "id", "name", "subscribed_fields", "fields", "object",
            "active", "success", "callback_url", "tasks", "category", "permissions",
            "version",
        }
        return {
            key: (
                safe_graph_diagnostics(item) if key in safe_fields else "<redacted>"
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [safe_graph_diagnostics(item) for item in value]
    return value


def page_access_token(page: FacebookPage) -> str:
    if not page.access_token_encrypted:
        raise FacebookTokenError("Page Access Token is unavailable")
    return TokenCipher().decrypt(page.access_token_encrypted)


def user_access_token_for_current_account(session: Session, user: User) -> str:
    account = get_active_account_for_user(session, user)
    if account is None:
        raise FacebookPageUnavailableError("Facebook account is not connected")
    return TokenCipher().decrypt(account.access_token_encrypted)


def permission_names(
    permissions_response: dict[str, Any],
    status_name: str,
) -> list[str]:
    data = permissions_response.get("data")
    if not isinstance(data, list):
        return []
    return sorted(
        str(item["permission"])
        for item in data
        if isinstance(item, dict)
        and item.get("permission")
        and item.get("status") == status_name
    )


def has_page_messages_subscription(subscriptions_response: dict[str, Any]) -> bool:
    subscriptions = subscriptions_response.get("data")
    if not isinstance(subscriptions, list):
        return False

    for subscription in subscriptions:
        if not isinstance(subscription, dict) or subscription.get("object") != "page":
            continue
        fields = subscription.get("fields")
        if not isinstance(fields, list):
            continue
        field_names = {
            str(field.get("name") if isinstance(field, dict) else field)
            for field in fields
        }
        if "messages" in field_names:
            return True
    return False


def subscribed_fields_for_app(graph_response: dict[str, Any], app_id: str) -> list[str]:
    data = graph_response.get("data")
    if not isinstance(data, list):
        return []
    for item in data:
        if not isinstance(item, dict) or str(item.get("id") or "") != app_id:
            continue
        fields = item.get("subscribed_fields")
        return [str(field) for field in fields] if isinstance(fields, list) else []
    return []


def configured_webhook_callback_url() -> str:
    settings = get_settings()
    if settings.facebook_webhook_callback_url:
        return settings.facebook_webhook_callback_url

    redirect = urlsplit(settings.facebook_redirect_uri)
    if not redirect.scheme or not redirect.netloc:
        return ""
    return urlunsplit(
        (
            redirect.scheme,
            redirect.netloc,
            "/api/v1/facebook/webhook",
            "",
            "",
        )
    )


def app_webhook_callback(subscriptions_response: dict[str, Any]) -> str | None:
    subscriptions = subscriptions_response.get("data")
    if not isinstance(subscriptions, list):
        return None
    for subscription in subscriptions:
        if not isinstance(subscription, dict) or subscription.get("object") != "page":
            continue
        callback = subscription.get("callback_url") or subscription.get("callback_uri")
        if callback:
            return str(callback)
    return None


def account_page_data(accounts_response: dict[str, Any], page_id: str) -> dict[str, Any]:
    pages = accounts_response.get("data")
    if not isinstance(pages, list):
        return {}
    return next(
        (
            item
            for item in pages
            if isinstance(item, dict) and str(item.get("id") or "") == page_id
        ),
        {},
    )


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


@router.get("/debug/subscribed-apps/{page_id}")
def debug_subscribed_apps(
    page_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    settings = get_settings()
    try:
        page = get_page_for_user(session, current_user, page_id)
        token = page_access_token(page)
        graph_response = FacebookGraphClient().get(
            f"/{page.page_id}/subscribed_apps",
            access_token=token,
        )
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    return {
        "page_id": page.page_id,
        "app_id": settings.facebook_app_id,
        "subscribed_fields": subscribed_fields_for_app(
            graph_response,
            settings.facebook_app_id,
        ),
        "graph_response": safe_graph_diagnostics(graph_response),
    }


@router.get("/debug/token-scopes")
def debug_token_scopes(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.facebook_app_id or not settings.facebook_app_secret:
        raise http_error(FacebookConfigurationError("Facebook App credentials are not configured"))

    try:
        token = user_access_token_for_current_account(session, current_user)
        graph = FacebookGraphClient()
        debug_response = graph.get(
            "/debug_token",
            {"input_token": token},
            access_token=f"{settings.facebook_app_id}|{settings.facebook_app_secret}",
        )
        permissions_response = graph.get("/me/permissions", access_token=token)
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    debug_data = debug_response.get("data")
    if not isinstance(debug_data, dict):
        debug_data = {}
    granted_scopes = permission_names(permissions_response, "granted")
    if not granted_scopes:
        debug_scopes = debug_data.get("scopes")
        if isinstance(debug_scopes, list):
            granted_scopes = sorted(str(scope) for scope in debug_scopes)

    return {
        "token_type": str(debug_data.get("type") or "unknown"),
        "app_id": str(debug_data.get("app_id") or ""),
        "user_id": str(debug_data.get("user_id") or ""),
        "granted_scopes": granted_scopes,
        "declined_scopes": permission_names(permissions_response, "declined"),
        "expires_at": debug_data.get("expires_at"),
    }


@router.get("/debug/page-permissions/{page_id}")
def debug_page_permissions(
    page_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    try:
        page = get_page_for_user(session, current_user, page_id)
        page_token = page_access_token(page)
        user_token = TokenCipher().decrypt(page.facebook_account.access_token_encrypted)
        graph = FacebookGraphClient()
        page_response = graph.get(
            f"/{page.page_id}",
            {"fields": "id,name,category"},
            access_token=page_token,
        )
        accounts_response = graph.get(
            "/me/accounts",
            {"fields": "id,name,category,tasks"},
            access_token=user_token,
        )
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    account_page: dict[str, Any] = {}
    account_pages = accounts_response.get("data")
    if isinstance(account_pages, list):
        account_page = next(
            (
                item
                for item in account_pages
                if isinstance(item, dict)
                and str(item.get("id") or "") == page.page_id
            ),
            {},
        )

    permissions = page_response.get("permissions", account_page.get("permissions"))
    return {
        "page_id": str(page_response.get("id") or page.page_id),
        "page_name": str(page_response.get("name") or account_page.get("name") or page.name),
        "tasks": account_page.get("tasks", []),
        "category": page_response.get("category", account_page.get("category")),
        "permissions": permissions,
    }


@router.get("/debug/page-info/{page_id}")
def debug_page_info(
    page_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    try:
        page = get_page_for_user(session, current_user, page_id)
        page_token = page_access_token(page)
        user_token = TokenCipher().decrypt(page.facebook_account.access_token_encrypted)
        graph = FacebookGraphClient(api_version=MESSENGER_DIAGNOSTICS_GRAPH_VERSION)
        page_response = graph.get(
            f"/{page.page_id}",
            {"fields": "id,name,category"},
            access_token=page_token,
        )
        accounts_response = graph.get(
            "/me/accounts",
            {"fields": "id,name,tasks"},
            access_token=user_token,
        )
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    account_page = account_page_data(accounts_response, page.page_id)
    tasks = account_page.get("tasks")
    return {
        "graph_api_version": MESSENGER_DIAGNOSTICS_GRAPH_VERSION,
        "id": str(page_response.get("id") or page.page_id),
        "name": str(page_response.get("name") or page.name),
        "category": page_response.get("category"),
        "tasks": [str(task) for task in tasks] if isinstance(tasks, list) else "UNKNOWN",
        "field_sources": {
            "id_name_category": f"GET /{page.page_id} with Page Access Token",
            "tasks": "GET /me/accounts with User Access Token",
        },
    }


@router.get("/debug/app-mode")
def debug_app_mode(
    _current_user: Annotated[User, Depends(require_active_user)],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.facebook_app_id or not settings.facebook_app_secret:
        raise http_error(FacebookConfigurationError("Facebook App credentials are not configured"))

    app_access_token = f"{settings.facebook_app_id}|{settings.facebook_app_secret}"
    try:
        graph = FacebookGraphClient()
        app_response = graph.get(
            f"/{settings.facebook_app_id}",
            {"fields": "id,name"},
            access_token=app_access_token,
        )
        subscriptions_response = graph.get(
            f"/{settings.facebook_app_id}/subscriptions",
            access_token=app_access_token,
        )
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    return {
        "app_id": str(app_response.get("id") or settings.facebook_app_id),
        "app_name": str(app_response.get("name") or ""),
        "app_mode": "unknown",
        "has_messenger_product": has_page_messages_subscription(subscriptions_response),
    }


@router.get("/debug/app-info")
def debug_app_info(
    _current_user: Annotated[User, Depends(require_active_user)],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.facebook_app_id or not settings.facebook_app_secret:
        raise http_error(FacebookConfigurationError("Facebook App credentials are not configured"))

    app_access_token = f"{settings.facebook_app_id}|{settings.facebook_app_secret}"
    try:
        graph = FacebookGraphClient(api_version=MESSENGER_DIAGNOSTICS_GRAPH_VERSION)
        app_response = graph.get(
            f"/{settings.facebook_app_id}",
            {"fields": "id,name"},
            access_token=app_access_token,
        )
        subscriptions_response = graph.get(
            f"/{settings.facebook_app_id}/subscriptions",
            access_token=app_access_token,
        )
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    return {
        "graph_api_version": MESSENGER_DIAGNOSTICS_GRAPH_VERSION,
        "app_id": str(app_response.get("id") or settings.facebook_app_id),
        "app_name": str(app_response.get("name") or ""),
        "app_mode": "UNKNOWN",
        "messenger_product_enabled": "UNKNOWN",
        "webhook_product_enabled": "UNKNOWN",
        "graph_evidence": {
            "page_messages_subscription_present": has_page_messages_subscription(
                subscriptions_response
            ),
            "app_subscriptions": safe_graph_diagnostics(subscriptions_response),
        },
        "unknown_reasons": [
            "Graph API does not expose a supported App Mode field.",
            "Graph API does not expose installed Messenger/Webhooks product switches.",
        ],
    }


@router.get("/debug/webhook-subscriptions")
def debug_webhook_subscriptions(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.facebook_app_id or not settings.facebook_app_secret:
        raise http_error(FacebookConfigurationError("Facebook App credentials are not configured"))

    account = get_active_account_for_user(session, current_user)
    if account is None:
        raise http_error(FacebookPageUnavailableError("Facebook account is not connected"))

    page = get_current_page(session, current_user)
    if (
        page is None
        or page.facebook_account_id != account.id
        or not page.is_active
        or page.deleted_at is not None
    ):
        active_pages = sorted(
            (
                candidate
                for candidate in account.pages
                if candidate.is_active and candidate.deleted_at is None
            ),
            key=lambda candidate: candidate.page_id,
        )
        if not active_pages:
            raise http_error(FacebookPageUnavailableError("No active Facebook Page is available"))
        page = active_pages[0]

    try:
        user_token = TokenCipher().decrypt(account.access_token_encrypted)
        page_token = page_access_token(page)
        app_access_token = f"{settings.facebook_app_id}|{settings.facebook_app_secret}"
        graph = FacebookGraphClient(api_version=MESSENGER_DIAGNOSTICS_GRAPH_VERSION)
        app_response = graph.get(
            f"/{settings.facebook_app_id}",
            {"fields": "id,name"},
            access_token=app_access_token,
        )
        app_subscriptions = graph.get(
            f"/{settings.facebook_app_id}/subscriptions",
            access_token=app_access_token,
        )
        page_subscriptions = graph.get(
            f"/{page.page_id}/subscribed_apps",
            access_token=page_token,
        )
        user_debug_response = graph.get(
            "/debug_token",
            {"input_token": user_token},
            access_token=app_access_token,
        )
        page_debug_response = graph.get(
            "/debug_token",
            {"input_token": page_token},
            access_token=app_access_token,
        )
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    user_debug_data = user_debug_response.get("data")
    if not isinstance(user_debug_data, dict):
        user_debug_data = {}
    page_debug_data = page_debug_response.get("data")
    if not isinstance(page_debug_data, dict):
        page_debug_data = {}

    page_subscription_app_ids = sorted(
        str(item.get("id"))
        for item in page_subscriptions.get("data", [])
        if isinstance(item, dict) and item.get("id")
    )
    app_ids: dict[str, str] = {
        "runtime_env": settings.facebook_app_id,
        "oauth": settings.facebook_app_id,
        "facebook_login": settings.facebook_app_id,
        "app_subscriptions_request": settings.facebook_app_id,
    }
    if app_response.get("id"):
        app_ids["application_node"] = str(app_response["id"])
    if user_debug_data.get("app_id"):
        app_ids["user_token"] = str(user_debug_data["app_id"])
    if page_debug_data.get("app_id"):
        app_ids["page_token"] = str(page_debug_data["app_id"])

    compared_ids = set(app_ids.values())
    subscribed_app_matches = settings.facebook_app_id in page_subscription_app_ids
    app_id_failures: list[str] = []
    if len(compared_ids) != 1:
        app_id_failures.append("OAuth/runtime/token App IDs are not identical.")
    if not subscribed_app_matches:
        app_id_failures.append("Configured App ID is absent from Page subscribed_apps.")
    graph_app_ids_complete = {
        "application_node",
        "user_token",
        "page_token",
    }.issubset(app_ids)
    if app_id_failures:
        app_id_status = "FAIL"
    elif not graph_app_ids_complete:
        app_id_status = "UNKNOWN"
    else:
        app_id_status = "PASS"

    return {
        "graph_api_version": MESSENGER_DIAGNOSTICS_GRAPH_VERSION,
        "page_id": page.page_id,
        "app_subscriptions": safe_graph_diagnostics(app_subscriptions),
        "page_subscriptions": safe_graph_diagnostics(page_subscriptions),
        "subscribed_fields": subscribed_fields_for_app(
            page_subscriptions,
            settings.facebook_app_id,
        ),
        "callback_url": app_webhook_callback(app_subscriptions) or "UNKNOWN",
        "app_id_consistency": {
            "status": app_id_status,
            "values": app_ids,
            "page_subscription_app_ids": page_subscription_app_ids,
            "failures": app_id_failures,
            "unknowns": (
                []
                if graph_app_ids_complete
                else [
                    "Graph did not expose the Application, User token, and Page token App IDs."
                ]
            ),
            "webhook_payload_app_id": "UNKNOWN",
            "webhook_payload_app_id_reason": (
                "Messenger webhook payloads and verification requests do not identify the App ID."
            ),
        },
        "source_code_evidence": {
            "oauth_client_id": "settings.facebook_app_id",
            "facebook_login_client_id": "settings.facebook_app_id",
            "page_subscription_match": subscribed_app_matches,
        },
    }


@router.get("/debug/messenger-diagnostics")
def debug_messenger_diagnostics(
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    settings = get_settings()
    graph_errors: list[dict[str, str]] = []
    failures: list[str] = []
    warnings: list[str] = []
    failed_checks: set[str] = set()

    graph = FacebookGraphClient(api_version=MESSENGER_DIAGNOSTICS_GRAPH_VERSION)

    def graph_get(
        check: str,
        path: str,
        *,
        access_token: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return graph.get(path, params, access_token=access_token)
        except FacebookIntegrationError as exc:
            failed_checks.add(check)
            graph_errors.append(
                {
                    "check": check,
                    "path": path,
                    "error_type": type(exc).__name__,
                    "message": "Facebook API request failed",
                }
            )
            logger.warning(
                "facebook_messenger_diagnostics_graph_error "
                "check={} path={} error_type={}",
                check,
                path,
                type(exc).__name__,
            )
            return {}

    app_access_token = ""
    if settings.facebook_app_id and settings.facebook_app_secret:
        app_access_token = f"{settings.facebook_app_id}|{settings.facebook_app_secret}"
    else:
        failures.append("Facebook App ID or App Secret is not configured.")

    account = get_active_account_for_user(session, current_user)
    page: FacebookPage | None = None
    if account is None:
        failures.append("No active Facebook account is connected for this user.")
    else:
        current_page = get_current_page(session, current_user)
        active_pages = sorted(
            (
                candidate
                for candidate in account.pages
                if candidate.is_active and candidate.deleted_at is None
            ),
            key=lambda candidate: candidate.page_id,
        )
        if (
            current_page is not None
            and current_page.facebook_account_id == account.id
            and current_page.is_active
            and current_page.deleted_at is None
        ):
            page = current_page
        elif active_pages:
            page = active_pages[0]
            warnings.append(
                f"No current Page is selected; diagnostics used active Page {page.page_id}."
            )
            if len(active_pages) > 1:
                warnings.append(
                    "Multiple active Pages exist; select the affected Page before rerunning "
                    "diagnostics."
                )
        else:
            failures.append("The connected Facebook account has no active Page.")

    user_token = ""
    if account is not None:
        try:
            user_token = TokenCipher().decrypt(account.access_token_encrypted)
        except FacebookIntegrationError as exc:
            failures.append(f"Stored User Access Token could not be read: {exc}")

    page_token = ""
    if page is not None:
        try:
            page_token = page_access_token(page)
        except FacebookIntegrationError as exc:
            failures.append(f"Stored Page Access Token could not be read: {exc}")

    app_response: dict[str, Any] = {}
    app_subscriptions: dict[str, Any] = {}
    if app_access_token:
        app_response = graph_get(
            "app",
            f"/{settings.facebook_app_id}",
            params={"fields": "id,name"},
            access_token=app_access_token,
        )
        app_subscriptions = graph_get(
            "app_subscriptions",
            f"/{settings.facebook_app_id}/subscriptions",
            access_token=app_access_token,
        )

    user_debug_response: dict[str, Any] = {}
    permissions_response: dict[str, Any] = {}
    accounts_response: dict[str, Any] = {}
    if user_token and app_access_token:
        user_debug_response = graph_get(
            "user_token",
            "/debug_token",
            params={"input_token": user_token},
            access_token=app_access_token,
        )
        permissions_response = graph_get(
            "user_permissions",
            "/me/permissions",
            access_token=user_token,
        )
        accounts_response = graph_get(
            "page_tasks",
            "/me/accounts",
            params={"fields": "id,name,tasks"},
            access_token=user_token,
        )

    page_debug_response: dict[str, Any] = {}
    page_response: dict[str, Any] = {}
    subscribed_apps: dict[str, Any] = {}
    if page is not None and page_token:
        if app_access_token:
            page_debug_response = graph_get(
                "page_token",
                "/debug_token",
                params={"input_token": page_token},
                access_token=app_access_token,
            )
        page_response = graph_get(
            "page",
            f"/{page.page_id}",
            params={"fields": "id,name"},
            access_token=page_token,
        )
        subscribed_apps = graph_get(
            "subscribed_apps",
            f"/{page.page_id}/subscribed_apps",
            access_token=page_token,
        )

    user_debug_data = user_debug_response.get("data")
    if not isinstance(user_debug_data, dict):
        user_debug_data = {}
    page_debug_data = page_debug_response.get("data")
    if not isinstance(page_debug_data, dict):
        page_debug_data = {}

    granted_scopes = permission_names(permissions_response, "granted")
    if not granted_scopes:
        debug_scopes = user_debug_data.get("scopes")
        if isinstance(debug_scopes, list):
            granted_scopes = sorted(str(scope) for scope in debug_scopes)
    declined_scopes = permission_names(permissions_response, "declined")

    selected_page_data = account_page_data(
        accounts_response,
        page.page_id if page is not None else "",
    )
    raw_tasks = selected_page_data.get("tasks")
    page_tasks = [str(task) for task in raw_tasks] if isinstance(raw_tasks, list) else []
    page_token_valid = (
        bool(page_debug_data.get("is_valid"))
        if page_debug_data and "page_token" not in failed_checks
        else None
    )
    webhook_callback = app_webhook_callback(app_subscriptions)
    messenger_product_status = (
        "unknown"
        if "app_subscriptions" in failed_checks or not app_access_token
        else "configured"
        if has_page_messages_subscription(app_subscriptions)
        else "not_detected"
    )

    if user_debug_data and not bool(user_debug_data.get("is_valid")):
        failures.append("The stored User Access Token is invalid or expired.")
    if page_token_valid is False:
        failures.append("The stored Page Access Token is invalid or expired.")

    missing_scopes = sorted(REQUIRED_MESSENGER_SCOPES.difference(granted_scopes))
    if "user_permissions" not in failed_checks and user_token and missing_scopes:
        failures.append(f"User token is missing required scopes: {', '.join(missing_scopes)}.")

    if "page_tasks" not in failed_checks and user_token and page is not None:
        if not MESSENGER_PAGE_TASKS.intersection(page_tasks):
            failures.append(
                "The User token does not expose a Messenger-capable task for this Page."
            )

    subscribed_fields = subscribed_fields_for_app(subscribed_apps, settings.facebook_app_id)
    if "subscribed_apps" not in failed_checks and page_token:
        if not subscribed_fields:
            failures.append(
                "The configured app is not present in the Page subscribed_apps response."
            )
        elif "messages" not in subscribed_fields:
            failures.append("The Page subscription does not include the messages field.")

    if messenger_product_status == "not_detected":
        failures.append("The app has no page webhook subscription containing the messages field.")

    configured_callback = configured_webhook_callback_url()
    if webhook_callback and configured_callback:
        if webhook_callback.rstrip("/") != configured_callback.rstrip("/"):
            failures.append(
                "The callback URL returned by Graph does not match the backend callback URL."
            )
    elif "app_subscriptions" not in failed_checks:
        warnings.append("Graph API did not expose a webhook callback URL for the app subscription.")

    critical_graph_checks = {
        "page_token",
        "page",
        "page_tasks",
        "subscribed_apps",
        "user_permissions",
        "user_token",
    }
    if failed_checks.intersection(critical_graph_checks):
        failures.append("One or more critical Graph API checks failed; inspect graph_errors.")
    if failed_checks.difference(critical_graph_checks):
        warnings.append("Some app-level Graph API checks failed; inspect graph_errors.")

    warnings.append(
        "Graph API does not reliably expose App Mode, Messenger product installation, "
        "or Advanced Access; verify these states in the Meta App Dashboard."
    )

    if failures:
        diagnosis = "FAIL"
        diagnosis_reasons = failures + warnings
    elif warnings:
        diagnosis = "WARNING"
        diagnosis_reasons = warnings
    else:
        diagnosis = "PASS"
        diagnosis_reasons = ["All Messenger delivery prerequisites exposed by Graph API passed."]

    return {
        "graph_api_version": MESSENGER_DIAGNOSTICS_GRAPH_VERSION,
        "app_id": str(app_response.get("id") or settings.facebook_app_id),
        "app_name": str(app_response.get("name") or ""),
        "page_id": page.page_id if page is not None else None,
        "page_name": str(page_response.get("name") or page.name) if page is not None else None,
        "page_tasks": page_tasks,
        "page_access_token_valid": page_token_valid,
        "user_token_scopes": {
            "token_type": str(user_debug_data.get("type") or "unknown"),
            "app_id": str(user_debug_data.get("app_id") or ""),
            "user_id": str(user_debug_data.get("user_id") or ""),
            "granted": granted_scopes,
            "declined": declined_scopes,
            "expires_at": user_debug_data.get("expires_at"),
        },
        "subscribed_apps": subscribed_apps,
        "app_subscriptions": safe_graph_diagnostics(app_subscriptions),
        "webhook_callback": webhook_callback,
        "configured_webhook_callback": configured_callback or None,
        "messenger_product_status": messenger_product_status,
        "graph_errors": graph_errors,
        "diagnosis": diagnosis,
        "diagnosis_reasons": diagnosis_reasons,
    }


@router.get("/debug/page-token/{page_id}")
def debug_page_token(
    page_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    try:
        page = get_page_for_user(session, current_user, page_id)
        token = page_access_token(page)
    except FacebookIntegrationError as exc:
        raise http_error(exc) from exc

    return {
        "page_id": page.page_id,
        "token_available": bool(token),
        "expires_at": page.token_expires_at,
    }


@router.post("/debug/resubscribe/{page_id}")
def debug_resubscribe(
    page_id: str,
    current_user: Annotated[User, Depends(require_active_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    try:
        page = get_page_for_user(session, current_user, page_id)
        token = page_access_token(page)
        request_path = f"/{page.page_id}/subscribed_apps"
        request_params = {
            "subscribed_fields": SUBSCRIBED_FIELDS,
            "access_token": "<redacted>",
        }
        logger.info(
            "facebook_debug_resubscribe_request path={} params={}",
            request_path,
            request_params,
        )
        graph_response = FacebookGraphClient().post(
            request_path,
            {
                "subscribed_fields": SUBSCRIBED_FIELDS,
                "access_token": token,
            },
        )
    except FacebookIntegrationError as exc:
        logger.warning(
            "facebook_debug_resubscribe_error error_type={}",
            type(exc).__name__,
        )
        raise http_error(exc) from exc

    logger.info("facebook_debug_resubscribe_response page_id={}", page.page_id)
    return {
        "page_id": page.page_id,
        "request_path": request_path,
        "graph_response": safe_graph_diagnostics(graph_response),
    }


@router.get("/debug/webhook-health")
def debug_webhook_health(
    request: Request,
    _current_user: Annotated[User, Depends(require_active_user)],
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "callback_url": configured_webhook_callback_url(),
        "verify_token_configured": bool(settings.facebook_webhook_verify_token),
        "app_secret_configured": bool(settings.facebook_app_secret),
        "cloudflare_reachable": True if request.headers.get("CF-Ray") else "unknown",
    }


@router.post("/debug/webhook-selftest")
async def debug_webhook_selftest(
    request: Request,
    _current_user: Annotated[User, Depends(require_active_user)],
) -> dict[str, Any]:
    request_id, signature_header, body = await read_and_log_webhook_request(request)
    logger.info(
        "facebook_webhook_selftest_accepted request_id={} body_length={} signature_present={}",
        request_id,
        len(body),
        bool(signature_header),
    )
    return {
        "received": True,
        "request_id": request_id,
        "body_length": len(body),
        "signature_present": bool(signature_header),
    }


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
