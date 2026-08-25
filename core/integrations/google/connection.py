"""Scope-aware principal-owned Google connection state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from core.connections import BuiltInConnectionService, GoogleConnection
from core.identity import ExecutionAuthority
from core.oauth import EncryptedOAuthStorage
from core.secrets import EncryptedSecretsService

GOOGLE_IDENTITY_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
)
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_OAUTH_NAMESPACE = "oauth.google"
_CLIENT_SECRET_KEY = "client-secret"
_TOKEN_STATE_KEY = "token-state"
_OAUTH_COLLECTION = "google"


class GoogleCapability(StrEnum):
    """Built-in capabilities backed by one Google connection."""

    GMAIL_READ = "gmail.read"

    @property
    def required_scopes(self) -> frozenset[str]:
        if self is GoogleCapability.GMAIL_READ:
            return frozenset((*GOOGLE_IDENTITY_SCOPES, GMAIL_READONLY_SCOPE))
        raise AssertionError(f"Unhandled Google capability: {self}")


@dataclass(frozen=True)
class GoogleOAuthTokenState:
    """Encrypted Google token grant and connected account identity."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: str | None = None
    scopes: tuple[str, ...] = ()
    token_type: str = "Bearer"
    account_id: str = field(default="", repr=False)
    account_email: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not str(self.access_token or "").strip():
            raise ValueError("Google access token cannot be empty.")
        if self.token_type.lower() != "bearer":
            raise ValueError("Google OAuth token type must be Bearer.")
        normalized_scopes = tuple(
            dict.fromkeys(scope.strip() for scope in self.scopes if scope.strip())
        )
        object.__setattr__(self, "scopes", normalized_scopes)
        if not str(self.account_id or "").strip():
            raise ValueError("Google account ID cannot be empty.")
        if not str(self.account_email or "").strip():
            raise ValueError("Google account email cannot be empty.")
        if self.expires_at is not None:
            _parse_timestamp(self.expires_at)

    @property
    def expired(self) -> bool:
        """Return whether the access token is known to be expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= _parse_timestamp(self.expires_at)

    @property
    def refreshable(self) -> bool:
        """Return whether durable access can continue after token expiry."""
        return bool(self.refresh_token)


@dataclass(frozen=True)
class GoogleConnectionStatus:
    """Sanitized status for one principal's Google connection."""

    state: Literal[
        "not_configured",
        "authorization_required",
        "ready",
        "reconnect_required",
    ]
    configured: bool
    connected: bool
    client_id: str | None
    client_secret_present: bool
    account_email: str | None
    granted_scopes: tuple[str, ...]
    config_version: int | None


@dataclass(frozen=True)
class GoogleCapabilityAvailability:
    """Scope-aware capability decision for effective tool binding."""

    capability: GoogleCapability
    available: bool
    connection_state: str
    missing_scopes: tuple[str, ...] = ()


class GoogleConnectionService:
    """Compose non-secret metadata with encrypted Google OAuth state."""

    def __init__(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
    ) -> None:
        self._connections = connections
        self._secrets = secrets

    def set_client_secret(
        self, authority: ExecutionAuthority, client_secret: str
    ) -> None:
        """Store a write-only Google OAuth client secret for one principal."""
        if self._connections.get_google_connection_for_authority(authority) is None:
            raise ValueError("Save Google connection configuration first.")
        clean_secret = str(client_secret or "").strip()
        if not clean_secret:
            raise ValueError("Google OAuth client secret cannot be empty.")
        self._storage(authority).put_sync(
            _CLIENT_SECRET_KEY,
            {"value": clean_secret},
            collection=_OAUTH_COLLECTION,
        )
        self.clear_token_state(authority)

    def resolve_client_secret(self, authority: ExecutionAuthority) -> str | None:
        """Resolve a client secret only beneath an explicit authority boundary."""
        payload = self._storage(authority).get_sync(
            _CLIENT_SECRET_KEY, collection=_OAUTH_COLLECTION
        )
        value = payload.get("value") if payload is not None else None
        return value if isinstance(value, str) and value else None

    def save_token_state(
        self, authority: ExecutionAuthority, token_state: GoogleOAuthTokenState
    ) -> None:
        """Persist a validated connected Google grant under principal authority."""
        if self._connections.get_google_connection_for_authority(authority) is None:
            raise ValueError("Google connection is not configured.")
        if self.resolve_client_secret(authority) is None:
            raise ValueError("Google OAuth client secret is not configured.")
        self._storage(authority).put_sync(
            _TOKEN_STATE_KEY,
            asdict(token_state),
            collection=_OAUTH_COLLECTION,
        )

    def load_token_state(
        self, authority: ExecutionAuthority
    ) -> GoogleOAuthTokenState | None:
        """Load and validate one principal's encrypted Google token grant."""
        payload = self._storage(authority).get_sync(
            _TOKEN_STATE_KEY, collection=_OAUTH_COLLECTION
        )
        if payload is None:
            return None
        try:
            scopes = payload.get("scopes", ())
            if not isinstance(scopes, list | tuple):
                raise TypeError
            return GoogleOAuthTokenState(
                access_token=str(payload["access_token"]),
                refresh_token=_optional_string(payload.get("refresh_token")),
                expires_at=_optional_string(payload.get("expires_at")),
                scopes=tuple(str(scope) for scope in scopes),
                token_type=str(payload.get("token_type") or "Bearer"),
                account_id=str(payload["account_id"]),
                account_email=str(payload["account_email"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Stored Google OAuth token state is invalid.") from exc

    def clear_token_state(self, authority: ExecutionAuthority) -> None:
        """Remove connected token/account state while preserving client setup."""
        self._storage(authority).delete_sync(
            _TOKEN_STATE_KEY, collection=_OAUTH_COLLECTION
        )

    def disconnect(self, authority: ExecutionAuthority) -> None:
        """Remove all encrypted Google OAuth material for one principal."""
        storage = self._storage(authority)
        for key in (_TOKEN_STATE_KEY, _CLIENT_SECRET_KEY):
            storage.delete_sync(key, collection=_OAUTH_COLLECTION)

    def status(self, authority: ExecutionAuthority) -> GoogleConnectionStatus:
        """Return sanitized configuration and authorization status."""
        connection = self._connections.get_google_connection_for_authority(authority)
        if connection is None:
            return _status_not_configured()
        client_secret_present = self.resolve_client_secret(authority) is not None
        token_state = self.load_token_state(authority)
        if not client_secret_present:
            return _status_for_connection(
                connection,
                state="not_configured",
                client_secret_present=False,
                token_state=None,
            )
        if token_state is None:
            return _status_for_connection(
                connection,
                state="authorization_required",
                client_secret_present=True,
                token_state=None,
            )
        state: Literal["ready", "reconnect_required"] = (
            "reconnect_required"
            if token_state.expired and not token_state.refreshable
            else "ready"
        )
        return _status_for_connection(
            connection,
            state=state,
            client_secret_present=True,
            token_state=token_state,
        )

    def capability_availability(
        self,
        authority: ExecutionAuthority,
        capability: GoogleCapability,
    ) -> GoogleCapabilityAvailability:
        """Resolve whether one capability should enter effective tool bindings."""
        status = self.status(authority)
        missing_scopes = tuple(
            sorted(capability.required_scopes.difference(status.granted_scopes))
        )
        return GoogleCapabilityAvailability(
            capability=capability,
            available=status.state == "ready" and not missing_scopes,
            connection_state=status.state,
            missing_scopes=missing_scopes,
        )

    def _storage(self, authority: ExecutionAuthority) -> EncryptedOAuthStorage:
        return EncryptedOAuthStorage(
            secrets=self._secrets,
            authority=authority,
            namespace=GOOGLE_OAUTH_NAMESPACE,
        )


def _status_not_configured() -> GoogleConnectionStatus:
    return GoogleConnectionStatus(
        state="not_configured",
        configured=False,
        connected=False,
        client_id=None,
        client_secret_present=False,
        account_email=None,
        granted_scopes=(),
        config_version=None,
    )


def _status_for_connection(
    connection: GoogleConnection,
    *,
    state: Literal[
        "not_configured",
        "authorization_required",
        "ready",
        "reconnect_required",
    ],
    client_secret_present: bool,
    token_state: GoogleOAuthTokenState | None,
) -> GoogleConnectionStatus:
    return GoogleConnectionStatus(
        state=state,
        configured=client_secret_present,
        connected=state == "ready",
        client_id=connection.client_id,
        client_secret_present=client_secret_present,
        account_email=(token_state.account_email if token_state is not None else None),
        granted_scopes=(token_state.scopes if token_state is not None else ()),
        config_version=connection.config_version,
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Google token expiry is invalid.") from exc
    if parsed.tzinfo is None:
        raise ValueError("Google token expiry must include a timezone.")
    return parsed.astimezone(UTC)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
