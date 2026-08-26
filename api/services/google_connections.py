"""Thin API projections for the principal-owned Google connection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from core.connections import (
    GmailPreferences,
    GoogleConnectionCreate,
    GoogleConnectionUpdate,
)
from core.identity import require_current_execution_authority
from core.integrations.google import GoogleCapability, GoogleOAuthCoordinator
from core.logger import UnifiedLogger
from core.oauth import parse_oauth_completion
from core.runtime.state import get_runtime_context

from ..exceptions import APIException
from ..models import (
    GoogleClientSecretUpdateRequest,
    GoogleConnectionCreateRequest,
    GoogleConnectionResponse,
    GoogleConnectionUpdateRequest,
    GoogleOAuthCompleteRequest,
    GoogleOAuthStartResponse,
    OperationResult,
)

logger = UnifiedLogger(tag="google-connections")
GOOGLE_OAUTH_CALLBACK_PATH = "/api/system/connections/google/oauth/callback"


def list_google_connections() -> list[GoogleConnectionResponse]:
    authority = require_current_execution_authority()
    runtime = get_runtime_context()
    return [
        _google_connection_response(connection.connection_id)
        for connection in runtime.built_in_connections.list_google_connections_for_authority(
            authority
        )
    ]


def create_google_connection(
    request: GoogleConnectionCreateRequest,
) -> GoogleConnectionResponse:
    with _domain_errors():
        connection = (
            get_runtime_context().built_in_connections.create_google_connection(
                GoogleConnectionCreate(
                    display_name=request.display_name,
                    client_id=request.client_id,
                    is_default=request.is_default,
                    gmail=GmailPreferences(**request.gmail.model_dump()),
                )
            )
        )
    return _google_connection_response(connection.connection_id)


def get_google_connection() -> GoogleConnectionResponse:
    """Return sanitized configuration and readiness for the request principal."""
    return _google_connection_response(None)


def get_google_connection_by_id(connection_id: str) -> GoogleConnectionResponse:
    with _domain_errors():
        connection = get_runtime_context().built_in_connections.get_google_connection_for_authority(
            require_current_execution_authority(), connection_id
        )
        if connection is None:
            raise LookupError("Google connection not found.")
    return _google_connection_response(connection.connection_id)


def _google_connection_response(
    connection_id: str | None,
) -> GoogleConnectionResponse:
    authority = require_current_execution_authority()
    runtime = get_runtime_context()
    connection = runtime.built_in_connections.get_google_connection_for_authority(
        authority, connection_id
    )
    service = runtime.google_connection
    if service is None:
        raise _secrets_locked()
    status = service.status(authority, connection_id)
    availability = service.capability_availability(
        authority, GoogleCapability.GMAIL_READ, connection_id
    )
    gmail = connection.gmail if connection is not None else GmailPreferences()
    return GoogleConnectionResponse.model_validate(
        {
            **asdict(status),
            "granted_scopes": list(status.granted_scopes),
            "gmail": asdict(gmail),
            "gmail_available": availability.available,
            "gmail_missing_scopes": list(availability.missing_scopes),
            "oauth_redirect_uri": _oauth_redirect_uri(
                connection_id=status.connection_id, required=False
            ),
        }
    )


def update_google_connection(
    request: GoogleConnectionUpdateRequest,
) -> GoogleConnectionResponse:
    """Persist non-secret Google client metadata and Gmail preferences."""
    with _domain_errors():
        connection = get_runtime_context().built_in_connections.set_google_connection(
            GoogleConnectionUpdate(
                client_id=request.client_id,
                display_name=request.display_name,
                is_default=request.is_default,
                gmail=GmailPreferences(**request.gmail.model_dump()),
            )
        )
    logger.info(
        "Google connection configuration changed",
        data={
            "event": "google_connection_updated",
            "config_version": connection.config_version,
        },
    )
    return get_google_connection()


def update_google_connection_by_id(
    connection_id: str, request: GoogleConnectionUpdateRequest
) -> GoogleConnectionResponse:
    with _domain_errors():
        get_runtime_context().built_in_connections.update_google_connection(
            connection_id,
            GoogleConnectionUpdate(
                client_id=request.client_id,
                display_name=request.display_name,
                is_default=request.is_default,
                gmail=GmailPreferences(**request.gmail.model_dump()),
            ),
        )
    return _google_connection_response(connection_id)


def set_google_client_secret(
    request: GoogleClientSecretUpdateRequest,
    connection_id: str | None = None,
) -> GoogleConnectionResponse:
    """Persist the write-only Google OAuth client secret."""
    service = get_runtime_context().google_connection
    if service is None:
        raise _secrets_locked()
    with _domain_errors():
        service.set_client_secret(
            require_current_execution_authority(),
            request.client_secret.get_secret_value(),
            connection_id,
        )
    logger.info(
        "Google OAuth client secret updated",
        data={"event": "google_oauth_client_secret_updated"},
    )
    return _google_connection_response(connection_id)


def start_google_oauth(connection_id: str | None = None) -> GoogleOAuthStartResponse:
    """Start authorization for the first Gmail read capability."""
    redirect_uri = _oauth_redirect_uri(connection_id=connection_id, required=True)
    if redirect_uri is None:  # pragma: no cover - guarded by required=True
        raise AssertionError("Required Google OAuth redirect URI was not resolved.")
    with _domain_errors():
        result = _oauth_coordinator().start(
            authority=require_current_execution_authority(),
            redirect_uri=redirect_uri,
            capabilities=(GoogleCapability.GMAIL_READ,),
            connection_id=connection_id,
        )
    logger.info("Google OAuth started", data={"event": "google_oauth_started"})
    payload = asdict(result)
    payload["requested_scopes"] = list(result.requested_scopes)
    return GoogleOAuthStartResponse.model_validate(payload)


async def complete_google_oauth(
    request: GoogleOAuthCompleteRequest,
    connection_id: str | None = None,
) -> GoogleConnectionResponse:
    """Complete one callback or pasted-redirect Google OAuth attempt."""
    with _domain_errors():
        code, state = parse_oauth_completion(
            redirect_url=request.redirect_url,
            code=request.code,
            state=request.state,
        )
        await _oauth_coordinator().complete(
            authority=require_current_execution_authority(),
            code=code,
            state=state,
            connection_id=connection_id,
        )
    logger.info("Google OAuth completed", data={"event": "google_oauth_completed"})
    return _google_connection_response(connection_id)


def disconnect_google_oauth(connection_id: str | None = None) -> OperationResult:
    """Clear the connected grant while preserving reusable client configuration."""
    service = get_runtime_context().google_connection
    if service is None:
        raise _secrets_locked()
    service.clear_token_state(require_current_execution_authority(), connection_id)
    logger.info(
        "Google OAuth disconnected", data={"event": "google_oauth_disconnected"}
    )
    return OperationResult(
        success=True,
        message="Google account disconnected.",
        restart_required=False,
    )


def delete_google_connection(
    connection_id: str | None = None,
    *,
    replacement_default_id: str | None = None,
) -> OperationResult:
    """Remove Google metadata and all encrypted Google credentials."""
    runtime = get_runtime_context()
    service = runtime.google_connection
    if service is None:
        raise _secrets_locked()
    authority = require_current_execution_authority()
    connection = runtime.built_in_connections.get_google_connection_for_authority(
        authority, connection_id
    )
    if connection is None:
        raise LookupError("Google connection not found.")
    runtime.built_in_connections.delete_google_connection_for_authority(
        authority,
        connection.connection_id,
        replacement_default_id=replacement_default_id,
    )
    service.disconnect_by_connection_id(authority, connection.connection_id)
    logger.info(
        "Google connection deleted", data={"event": "google_connection_deleted"}
    )
    return OperationResult(
        success=True,
        message="Google connection removed.",
        restart_required=False,
    )


def _oauth_coordinator() -> GoogleOAuthCoordinator:
    coordinator = get_runtime_context().google_oauth
    if coordinator is None:
        raise _secrets_locked()
    return coordinator


def _oauth_redirect_uri(*, connection_id: str | None, required: bool) -> str | None:
    public_origin = get_runtime_context().config.public_origin
    if public_origin is None:
        if required:
            raise APIException(
                status_code=409,
                error_type="PublicURLRequired",
                message=(
                    "Set ASSISTANTMD_PUBLIC_URL before starting Google OAuth so the "
                    "registered callback URI is stable."
                ),
            )
        return None
    callback_path = (
        f"/api/system/connections/google/connections/{connection_id}/oauth/callback"
        if connection_id is not None
        else GOOGLE_OAUTH_CALLBACK_PATH
    )
    return public_origin.build_url(callback_path)


def _secrets_locked() -> APIException:
    return APIException(
        status_code=503,
        error_type="SecretsLocked",
        message="Google connections are unavailable while encrypted secrets are locked.",
    )


@contextmanager
def _domain_errors() -> Iterator[None]:
    try:
        yield
    except APIException:
        raise
    except (LookupError, ValueError) as exc:
        raise APIException(
            status_code=400,
            error_type="InvalidGoogleConnection",
            message=str(exc),
        ) from exc
