"""OpenAI OAuth token and pending-auth state helpers."""

from __future__ import annotations

import json
import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

from core.settings.secrets_store import (
    delete_secret,
    get_secret_value,
    set_secret_value,
)


OPENAI_OAUTH_TOKEN_SECRET = "OPENAI_OAUTH_TOKEN_STATE"
OPENAI_OAUTH_PENDING_SECRET = "OPENAI_OAUTH_PENDING_STATE"
OPENAI_OAUTH_INTERNAL_SECRETS = frozenset(
    {OPENAI_OAUTH_TOKEN_SECRET, OPENAI_OAUTH_PENDING_SECRET}
)
OPENAI_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_OAUTH_PENDING_TTL_SECONDS = 600
OPENAI_OAUTH_CLIENT_ID = "codex-cli"


class OpenAIOAuthStateError(ValueError):
    """Raised when stored OpenAI OAuth state is malformed or unusable."""


@dataclass(frozen=True)
class OpenAIOAuthTokenState:
    """Persisted OAuth token state."""

    access_token: str
    refresh_token: str | None = None
    expires_at: str | None = None
    account_id: str | None = None
    last_refresh_at: str | None = None
    last_refresh_error: str | None = None


@dataclass(frozen=True)
class OpenAIOAuthPendingState:
    """Short-lived PKCE state for an in-progress OAuth connection."""

    state: str
    code_verifier: str
    redirect_uri: str
    created_at: str
    expires_at: str
    return_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenAIOAuthStartResult:
    """Bootstrap data for an OAuth connection attempt."""

    auth_url: str
    state: str
    redirect_uri: str
    expires_at: str


@dataclass(frozen=True)
class OpenAIOAuthStatus:
    """Sanitized OAuth connection status for API/UI surfaces."""

    connected: bool
    status: str
    has_refresh_token: bool = False
    account_id: str | None = None
    expires_at: str | None = None
    last_refresh_at: str | None = None
    last_refresh_error: str | None = None
    pending_expires_at: str | None = None


@dataclass(frozen=True)
class OpenAIOAuthTokenResult:
    """Token exchange or refresh result returned by adapter implementations."""

    access_token: str
    refresh_token: str | None = None
    expires_at: str | None = None
    account_id: str | None = None


class OpenAIOAuthTokenAdapter(Protocol):
    """Adapter boundary for real or fake token exchange and refresh."""

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OpenAIOAuthTokenResult:
        """Exchange an authorization code for OAuth tokens."""

    async def refresh_token(self, *, refresh_token: str) -> OpenAIOAuthTokenResult:
        """Refresh an OAuth access token."""


@dataclass(frozen=True)
class StaticOpenAIOAuthTokenAdapter:
    """Deterministic token adapter for validation and smoke tests."""

    token_result: OpenAIOAuthTokenResult

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OpenAIOAuthTokenResult:
        """Return the configured token result."""

        return self.token_result

    async def refresh_token(self, *, refresh_token: str) -> OpenAIOAuthTokenResult:
        """Return the configured token result."""

        return self.token_result


_token_adapter: OpenAIOAuthTokenAdapter | None = None


def set_openai_oauth_token_adapter(adapter: OpenAIOAuthTokenAdapter | None) -> None:
    """Set the process-local token adapter used by OAuth completion."""

    global _token_adapter
    _token_adapter = adapter


def get_openai_oauth_token_adapter() -> OpenAIOAuthTokenAdapter:
    """Return the configured token adapter or fail closed."""

    if _token_adapter is None:
        raise OpenAIOAuthStateError("OpenAI OAuth token adapter is not configured.")
    return _token_adapter


def is_openai_oauth_internal_secret(name: str) -> bool:
    """Return True when a secret name belongs to internal OpenAI OAuth state."""

    return name in OPENAI_OAUTH_INTERNAL_SECRETS


def start_openai_oauth(
    *,
    redirect_uri: str,
    now: datetime | None = None,
) -> OpenAIOAuthStartResult:
    """Create pending PKCE state and return OAuth bootstrap data."""

    reference = _normalize_datetime(now or datetime.now(UTC))
    expires_at = (reference + timedelta(seconds=OPENAI_OAUTH_PENDING_TTL_SECONDS))
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    pending = OpenAIOAuthPendingState(
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        created_at=reference.isoformat(),
        expires_at=expires_at.isoformat(),
    )
    save_openai_oauth_pending_state(pending)

    query = urlencode(
        {
            "response_type": "code",
            "client_id": OPENAI_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return OpenAIOAuthStartResult(
        auth_url=f"{OPENAI_OAUTH_AUTHORIZE_URL}?{query}",
        state=state,
        redirect_uri=redirect_uri,
        expires_at=expires_at.isoformat(),
    )


async def complete_openai_oauth(
    *,
    code: str,
    state: str,
    adapter: OpenAIOAuthTokenAdapter | None = None,
    now: datetime | None = None,
) -> OpenAIOAuthTokenState:
    """Consume pending PKCE state and persist exchanged OAuth tokens."""

    pending = consume_openai_oauth_pending_state(state=state, now=now)
    token_adapter = adapter or get_openai_oauth_token_adapter()
    token_result = await token_adapter.exchange_code(
        code=code,
        code_verifier=pending.code_verifier,
        redirect_uri=pending.redirect_uri,
    )
    token_state = token_result_to_state(token_result)
    save_openai_oauth_token_state(token_state)
    return token_state


async def complete_openai_oauth_from_redirect(
    *,
    redirect_url: str | None = None,
    code: str | None = None,
    state: str | None = None,
    adapter: OpenAIOAuthTokenAdapter | None = None,
    now: datetime | None = None,
) -> OpenAIOAuthTokenState:
    """Complete OAuth from a pasted redirect URL or raw code/state pair."""

    resolved_code = code
    resolved_state = state
    if redirect_url:
        parsed_code, parsed_state = _parse_redirect_values(redirect_url)
        resolved_code = parsed_code
        resolved_state = parsed_state

    if not resolved_code:
        raise OpenAIOAuthStateError("OpenAI OAuth completion requires a code.")

    if not resolved_state:
        pending = load_openai_oauth_pending_state(now=now, cleanup_expired=True)
        if pending is None:
            raise OpenAIOAuthStateError(
                "OpenAI OAuth completion requires state when no pending attempt exists."
            )
        resolved_state = pending.state

    return await complete_openai_oauth(
        code=resolved_code,
        state=resolved_state,
        adapter=adapter,
        now=now,
    )


def save_openai_oauth_token_state(state: OpenAIOAuthTokenState) -> None:
    """Persist OpenAI OAuth token state as an internal secret."""

    if not state.access_token.strip():
        raise OpenAIOAuthStateError("OpenAI OAuth access token cannot be empty.")
    set_secret_value(
        OPENAI_OAUTH_TOKEN_SECRET,
        json.dumps(_token_state_to_dict(state), separators=(",", ":")),
    )


def load_openai_oauth_token_state() -> OpenAIOAuthTokenState | None:
    """Load stored OpenAI OAuth token state, if present."""

    payload = get_secret_value(OPENAI_OAUTH_TOKEN_SECRET)
    if not payload:
        return None
    raw = _load_json_mapping(payload, "OpenAI OAuth token state")
    access_token = _required_string(raw, "access_token", "OpenAI OAuth token state")
    return OpenAIOAuthTokenState(
        access_token=access_token,
        refresh_token=_optional_string(raw, "refresh_token"),
        expires_at=_optional_string(raw, "expires_at"),
        account_id=_optional_string(raw, "account_id"),
        last_refresh_at=_optional_string(raw, "last_refresh_at"),
        last_refresh_error=_optional_string(raw, "last_refresh_error"),
    )


def clear_openai_oauth_token_state() -> None:
    """Delete stored OpenAI OAuth token state."""

    delete_secret(OPENAI_OAUTH_TOKEN_SECRET)


def save_openai_oauth_pending_state(state: OpenAIOAuthPendingState) -> None:
    """Persist one pending OpenAI OAuth connection attempt."""

    _parse_datetime(state.expires_at, "expires_at")
    set_secret_value(
        OPENAI_OAUTH_PENDING_SECRET,
        json.dumps(_pending_state_to_dict(state), separators=(",", ":")),
    )


def load_openai_oauth_pending_state(
    *,
    now: datetime | None = None,
    cleanup_expired: bool = True,
) -> OpenAIOAuthPendingState | None:
    """Load pending OAuth state, deleting it when expired by lazy TTL cleanup."""

    payload = get_secret_value(OPENAI_OAUTH_PENDING_SECRET)
    if not payload:
        return None
    pending = _pending_state_from_payload(payload)
    if _is_expired(pending.expires_at, now=now):
        if cleanup_expired:
            clear_openai_oauth_pending_state()
        return None
    return pending


def consume_openai_oauth_pending_state(
    *,
    state: str,
    now: datetime | None = None,
) -> OpenAIOAuthPendingState:
    """Return and delete matching pending state, enforcing TTL and single use."""

    pending = load_openai_oauth_pending_state(now=now, cleanup_expired=True)
    if pending is None:
        raise OpenAIOAuthStateError("No active OpenAI OAuth connection attempt.")
    if pending.state != state:
        raise OpenAIOAuthStateError("OpenAI OAuth state did not match.")
    clear_openai_oauth_pending_state()
    return pending


def clear_openai_oauth_pending_state() -> None:
    """Delete stored pending OAuth state."""

    delete_secret(OPENAI_OAUTH_PENDING_SECRET)


def clear_openai_oauth_state() -> None:
    """Delete all internal OpenAI OAuth token and pending state."""

    clear_openai_oauth_token_state()
    clear_openai_oauth_pending_state()


def get_openai_oauth_status(now: datetime | None = None) -> OpenAIOAuthStatus:
    """Return sanitized OpenAI OAuth status."""

    token_state = load_openai_oauth_token_state()
    pending_state = load_openai_oauth_pending_state(now=now, cleanup_expired=True)

    if token_state is not None:
        status = "refresh_failed" if token_state.last_refresh_error else "connected"
        return OpenAIOAuthStatus(
            connected=True,
            status=status,
            has_refresh_token=bool(token_state.refresh_token),
            account_id=token_state.account_id,
            expires_at=token_state.expires_at,
            last_refresh_at=token_state.last_refresh_at,
            last_refresh_error=token_state.last_refresh_error,
            pending_expires_at=(
                pending_state.expires_at if pending_state is not None else None
            ),
        )

    if pending_state is not None:
        return OpenAIOAuthStatus(
            connected=False,
            status="pending",
            pending_expires_at=pending_state.expires_at,
        )

    return OpenAIOAuthStatus(connected=False, status="disconnected")


def token_result_to_state(
    result: OpenAIOAuthTokenResult,
    *,
    previous: OpenAIOAuthTokenState | None = None,
    refreshed_at: str | None = None,
    refresh_error: str | None = None,
) -> OpenAIOAuthTokenState:
    """Convert an adapter token result into persisted state."""

    return OpenAIOAuthTokenState(
        access_token=result.access_token,
        refresh_token=result.refresh_token
        if result.refresh_token is not None
        else previous.refresh_token if previous is not None else None,
        expires_at=result.expires_at,
        account_id=result.account_id
        if result.account_id is not None
        else previous.account_id if previous is not None else None,
        last_refresh_at=refreshed_at,
        last_refresh_error=refresh_error,
    )


def _token_state_to_dict(state: OpenAIOAuthTokenState) -> dict[str, Any]:
    return {
        "access_token": state.access_token,
        "refresh_token": state.refresh_token,
        "expires_at": state.expires_at,
        "account_id": state.account_id,
        "last_refresh_at": state.last_refresh_at,
        "last_refresh_error": state.last_refresh_error,
    }


def _pending_state_to_dict(state: OpenAIOAuthPendingState) -> dict[str, Any]:
    return {
        "state": state.state,
        "code_verifier": state.code_verifier,
        "redirect_uri": state.redirect_uri,
        "created_at": state.created_at,
        "expires_at": state.expires_at,
        "return_metadata": state.return_metadata,
    }


def _pending_state_from_payload(payload: str) -> OpenAIOAuthPendingState:
    raw = _load_json_mapping(payload, "OpenAI OAuth pending state")
    return_metadata = raw.get("return_metadata", {})
    if not isinstance(return_metadata, dict):
        return_metadata = {}
    return OpenAIOAuthPendingState(
        state=_required_string(raw, "state", "OpenAI OAuth pending state"),
        code_verifier=_required_string(
            raw, "code_verifier", "OpenAI OAuth pending state"
        ),
        redirect_uri=_required_string(raw, "redirect_uri", "OpenAI OAuth pending state"),
        created_at=_required_string(raw, "created_at", "OpenAI OAuth pending state"),
        expires_at=_required_string(raw, "expires_at", "OpenAI OAuth pending state"),
        return_metadata=return_metadata,
    )


def _load_json_mapping(payload: str, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OpenAIOAuthStateError(f"{label} is not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise OpenAIOAuthStateError(f"{label} must be a JSON object.")
    return raw


def _required_string(raw: dict[str, Any], key: str, label: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OpenAIOAuthStateError(f"{label} missing required field '{key}'.")
    return value


def _optional_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _is_expired(expires_at: str, *, now: datetime | None = None) -> bool:
    expiry = _parse_datetime(expires_at, "expires_at")
    reference = _normalize_datetime(now or datetime.now(UTC))
    return expiry <= reference


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OpenAIOAuthStateError(
            f"OpenAI OAuth {field_name} must be an ISO 8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _parse_redirect_values(redirect_url: str) -> tuple[str | None, str | None]:
    parsed = urlparse(redirect_url)
    query = parse_qs(parsed.query)
    code = _single_query_value(query, "code")
    state = _single_query_value(query, "state")
    return code, state


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    if not values:
        return None
    value = values[0].strip()
    return value or None
