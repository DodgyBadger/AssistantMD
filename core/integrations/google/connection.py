"""Scope-aware principal-owned Google connection state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from core.connections import BuiltInConnectionService, GoogleConnection
from core.identity import ExecutionAuthority
from core.logger import UnifiedLogger
from core.oauth import EncryptedOAuthStorage
from core.secrets import (
    EncryptedSecretsService,
    SecretGuardMismatchError,
    SecretNamespaceDeletion,
)

GOOGLE_IDENTITY_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
)
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_OAUTH_NAMESPACE = "oauth.google"
_CLIENT_SECRET_KEY = "client-secret"
_TOKEN_STATE_KEY = "token-state"
GOOGLE_OAUTH_PENDING_KEY = "pending-authorization"
_OAUTH_COLLECTION = "google"

logger = UnifiedLogger(tag="google-connections")


class GoogleCredentialChangedError(ValueError):
    """Raised when an OAuth result no longer matches the active credential."""


class GoogleOAuthStateChangedError(ValueError):
    """Raised when an OAuth persistence source changes before commit."""


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
class GoogleOAuthClientCredential:
    """Current client secret and its metadata-generation binding."""

    value: str = field(repr=False)
    oauth_generation: int
    credential_id: str = field(repr=False)


@dataclass(frozen=True)
class GoogleConnectionStatus:
    """Sanitized status for one principal's Google connection."""

    state: Literal[
        "not_configured",
        "authorization_required",
        "ready",
        "reconnect_required",
    ]
    connection_id: str | None
    slug: str | None
    display_name: str | None
    is_default: bool
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
        self,
        authority: ExecutionAuthority,
        client_secret: str,
        connection_id: str | None = None,
    ) -> None:
        """Store a write-only Google OAuth client secret for one principal."""
        connection = self._connection(authority, connection_id)
        if connection is None:
            raise ValueError("Save Google connection configuration first.")
        clean_secret = str(client_secret or "").strip()
        if not clean_secret:
            raise ValueError("Google OAuth client secret cannot be empty.")
        credential_id = str(uuid4())
        credential_payload = {
            "value": clean_secret,
            "oauth_generation": connection.oauth_generation,
            "credential_id": credential_id,
        }
        self._storage(authority, connection.connection_id).replace_and_delete_sync(
            _CLIENT_SECRET_KEY,
            credential_payload,
            delete_keys=(_TOKEN_STATE_KEY, GOOGLE_OAUTH_PENDING_KEY),
            collection=_OAUTH_COLLECTION,
        )
        current = self._connection(authority, connection.connection_id)
        if current is not None and (
            current.oauth_generation == connection.oauth_generation
        ):
            return
        try:
            self._storage(authority, connection.connection_id).delete_sync_if_unchanged(
                _CLIENT_SECRET_KEY,
                credential_payload,
                collection=_OAUTH_COLLECTION,
            )
        except SecretGuardMismatchError:
            pass

    def handle_metadata_update(
        self,
        authority: ExecutionAuthority,
        previous: GoogleConnection,
        updated: GoogleConnection,
    ) -> None:
        """Apply OAuth invalidation after an authoritative metadata update."""
        if previous.oauth_generation == updated.oauth_generation:
            return
        current = self._connection(authority, updated.connection_id)
        if current is None or current.oauth_generation != updated.oauth_generation:
            logger.info(
                "Google OAuth identity cleanup superseded",
                data={
                    "event": "google_oauth_identity_cleanup_superseded",
                    "connection_id": updated.connection_id,
                    "oauth_generation": updated.oauth_generation,
                },
            )
            return
        storage = self._storage(authority, updated.connection_id)
        stored_credential = storage.get_sync(
            _CLIENT_SECRET_KEY, collection=_OAUTH_COLLECTION
        )
        try:
            credential_is_current = stored_credential is not None and (
                stored_credential.get("oauth_generation") == updated.oauth_generation
            )
            if not credential_is_current:
                if stored_credential is not None:
                    storage.replace_and_delete_sync(
                        _CLIENT_SECRET_KEY,
                        stored_credential,
                        delete_keys=(_TOKEN_STATE_KEY, GOOGLE_OAUTH_PENDING_KEY),
                        collection=_OAUTH_COLLECTION,
                        expected_value=stored_credential,
                    )
                    storage.delete_sync_if_unchanged(
                        _CLIENT_SECRET_KEY,
                        stored_credential,
                        collection=_OAUTH_COLLECTION,
                    )
        except Exception as exc:
            logger.warning(
                "Stale Google OAuth identity cleanup deferred",
                data={
                    "event": "google_oauth_stale_cleanup_deferred",
                    "connection_id": updated.connection_id,
                    "error_type": type(exc).__name__,
                },
            )
        logger.info(
            "Google OAuth client identity changed",
            data={
                "event": "google_oauth_identity_changed",
                "connection_id": updated.connection_id,
                "config_version": updated.config_version,
                "oauth_generation": updated.oauth_generation,
                "status": "invalidated",
            },
        )

    def resolve_client_secret(
        self, authority: ExecutionAuthority, connection_id: str | None = None
    ) -> str | None:
        """Resolve a client secret only beneath an explicit authority boundary."""
        connection = self._connection(authority, connection_id)
        if connection is None:
            return None
        credential = self.resolve_client_credential(authority, connection.connection_id)
        return credential.value if credential is not None else None

    def resolve_client_credential(
        self, authority: ExecutionAuthority, connection_id: str | None = None
    ) -> GoogleOAuthClientCredential | None:
        """Resolve a client secret only when bound to current metadata."""
        for _attempt in range(3):
            connection = self._connection(authority, connection_id)
            if connection is None:
                return None
            payload = self._load_connection_payload(
                authority, connection, _CLIENT_SECRET_KEY
            )
            if payload is None:
                return None
            value = payload.get("value")
            if not isinstance(value, str) or not value:
                return None
            generation = payload.get("oauth_generation")
            credential_id = payload.get("credential_id")
            if generation is None and credential_id is None:
                credential_id = str(uuid4())
                upgraded_payload = {
                    "value": value,
                    "oauth_generation": connection.oauth_generation,
                    "credential_id": credential_id,
                }
                storage = self._storage(authority, connection.connection_id)
                try:
                    storage.put_sync_if_unchanged(
                        _CLIENT_SECRET_KEY,
                        upgraded_payload,
                        guard_key=_CLIENT_SECRET_KEY,
                        expected_guard_value=payload,
                        collection=_OAUTH_COLLECTION,
                        guard_collection=_OAUTH_COLLECTION,
                    )
                except SecretGuardMismatchError:
                    continue
                current = self._connection(authority, connection.connection_id)
                current_payload = storage.get_sync(
                    _CLIENT_SECRET_KEY, collection=_OAUTH_COLLECTION
                )
                if current is None or (
                    current.oauth_generation != connection.oauth_generation
                ):
                    try:
                        storage.delete_sync_if_unchanged(
                            _CLIENT_SECRET_KEY,
                            upgraded_payload,
                            collection=_OAUTH_COLLECTION,
                        )
                    except SecretGuardMismatchError:
                        pass
                    return None
                if current_payload != upgraded_payload:
                    continue
                payload = upgraded_payload
                generation = connection.oauth_generation
            if (
                generation != connection.oauth_generation
                or not isinstance(credential_id, str)
                or not credential_id
            ):
                return None
            return GoogleOAuthClientCredential(
                value=value,
                oauth_generation=connection.oauth_generation,
                credential_id=credential_id,
            )
        raise GoogleOAuthStateChangedError(
            "Google OAuth credential changed repeatedly while it was resolved."
        )

    def save_token_state(
        self,
        authority: ExecutionAuthority,
        token_state: GoogleOAuthTokenState,
        connection_id: str | None = None,
        *,
        expected_credential: GoogleOAuthClientCredential | None = None,
        expected_token_state: GoogleOAuthTokenState | None = None,
    ) -> None:
        """Persist a validated connected Google grant under principal authority."""
        connection = self._connection(authority, connection_id)
        if connection is None:
            raise ValueError("Google connection is not configured.")
        credential = self.resolve_client_credential(authority, connection.connection_id)
        if expected_credential is not None and credential != expected_credential:
            raise GoogleCredentialChangedError(
                "Google OAuth client credential changed during authorization."
            )
        if credential is None:
            raise ValueError("Google OAuth client secret is not configured.")
        payload = _token_payload(token_state, credential)
        expected_token_payload: dict[str, object] | None = None
        if expected_token_state is not None:
            if expected_credential is None:
                raise ValueError("Expected token state requires a credential binding.")
            expected_token_payload = _token_payload(
                expected_token_state, expected_credential
            )
        storage = self._storage(authority, connection.connection_id)
        if expected_credential is None:
            storage.put_sync(
                _TOKEN_STATE_KEY,
                payload,
                collection=_OAUTH_COLLECTION,
            )
            return
        try:
            storage.put_sync_if_unchanged(
                _TOKEN_STATE_KEY,
                payload,
                guard_key=_CLIENT_SECRET_KEY,
                expected_guard_value={
                    "value": expected_credential.value,
                    "oauth_generation": expected_credential.oauth_generation,
                    "credential_id": expected_credential.credential_id,
                },
                collection=_OAUTH_COLLECTION,
                guard_collection=_OAUTH_COLLECTION,
                additional_guard_key=(
                    _TOKEN_STATE_KEY if expected_token_state is not None else None
                ),
                additional_expected_guard_value=(expected_token_payload),
            )
        except SecretGuardMismatchError as exc:
            raise GoogleOAuthStateChangedError(
                "Google OAuth state changed while an external request was in flight."
            ) from exc

    def load_token_state(
        self, authority: ExecutionAuthority, connection_id: str | None = None
    ) -> GoogleOAuthTokenState | None:
        """Load and validate one principal's encrypted Google token grant."""
        connection = self._connection(authority, connection_id)
        if connection is None:
            return None
        credential = self.resolve_client_credential(authority, connection.connection_id)
        if credential is None:
            return None
        payload = self._load_connection_payload(authority, connection, _TOKEN_STATE_KEY)
        if payload is None:
            return None
        if not _payload_matches_credential(payload, credential):
            self._discard_stale_payload(
                authority,
                connection,
                _TOKEN_STATE_KEY,
            )
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

    def clear_token_state(
        self, authority: ExecutionAuthority, connection_id: str | None = None
    ) -> None:
        """Remove connected token/account state while preserving client setup."""
        for _attempt in range(3):
            connection = self._connection(authority, connection_id)
            if connection is None:
                return
            credential = self.resolve_client_credential(
                authority, connection.connection_id
            )
            if credential is None:
                self._delete_connection_keys(
                    authority,
                    connection,
                    (_TOKEN_STATE_KEY, GOOGLE_OAUTH_PENDING_KEY),
                )
                return
            current_payload = {
                "value": credential.value,
                "oauth_generation": credential.oauth_generation,
                "credential_id": credential.credential_id,
            }
            try:
                self._storage(
                    authority, connection.connection_id
                ).replace_and_delete_sync(
                    _CLIENT_SECRET_KEY,
                    {**current_payload, "credential_id": str(uuid4())},
                    delete_keys=(_TOKEN_STATE_KEY, GOOGLE_OAUTH_PENDING_KEY),
                    collection=_OAUTH_COLLECTION,
                    expected_value=current_payload,
                )
                return
            except SecretGuardMismatchError:
                continue
        raise GoogleOAuthStateChangedError(
            "Google OAuth configuration changed repeatedly during disconnect."
        )

    def disconnect(
        self, authority: ExecutionAuthority, connection_id: str | None = None
    ) -> None:
        """Remove all encrypted Google OAuth material for one principal."""
        connection = self._connection(authority, connection_id)
        if connection is None:
            return
        self.disconnect_by_connection_id(authority, connection.connection_id)

    def disconnect_by_connection_id(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        """Remove scoped OAuth material for an authorized connection ID."""
        connection = self._connection(authority, connection_id)
        if connection is None:
            return
        self.delete_connection_state(authority, connection)

    def delete_connection_state(
        self,
        authority: ExecutionAuthority,
        connection: GoogleConnection,
    ) -> None:
        """Delete captured connection state even after metadata removal."""
        self._delete_connection_keys(
            authority,
            connection,
            (_TOKEN_STATE_KEY, _CLIENT_SECRET_KEY, GOOGLE_OAUTH_PENDING_KEY),
        )

    def clear_legacy_state(self, authority: ExecutionAuthority) -> None:
        """Clear unscoped legacy OAuth state before changing the default."""
        EncryptedOAuthStorage(
            secrets=self._secrets,
            authority=authority,
            namespace=GOOGLE_OAUTH_NAMESPACE,
        ).delete_many_sync(
            (_TOKEN_STATE_KEY, _CLIENT_SECRET_KEY, GOOGLE_OAUTH_PENDING_KEY),
            collection=_OAUTH_COLLECTION,
        )

    def reconcile_connection_deletions(self) -> None:
        """Finish durable encrypted cleanup for deleted connection metadata."""
        for (
            authority,
            connection_id,
        ) in self._connections.list_google_connection_deletions():
            self.reconcile_connection_deletion(authority, connection_id)

    def reconcile_connection_deletion(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        """Finish one durable Google connection deletion idempotently."""
        self._secrets.mutate_for_authority(
            authority,
            namespace_deletions=(
                SecretNamespaceDeletion(f"{GOOGLE_OAUTH_NAMESPACE}.{connection_id}"),
            ),
        )

    def status(
        self, authority: ExecutionAuthority, connection_id: str | None = None
    ) -> GoogleConnectionStatus:
        """Return sanitized configuration and authorization status."""
        connection = self._connection(authority, connection_id)
        if connection is None:
            return _status_not_configured()
        client_secret_present = (
            self.resolve_client_secret(authority, connection.connection_id) is not None
        )
        token_state = self.load_token_state(authority, connection.connection_id)
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
        connection_id: str | None = None,
    ) -> GoogleCapabilityAvailability:
        """Resolve whether one capability should enter effective tool bindings."""
        status = self.status(authority, connection_id)
        missing_scopes = tuple(
            sorted(capability.required_scopes.difference(status.granted_scopes))
        )
        return GoogleCapabilityAvailability(
            capability=capability,
            available=status.state == "ready" and not missing_scopes,
            connection_state=status.state,
            missing_scopes=missing_scopes,
        )

    def any_capability_available(
        self, authority: ExecutionAuthority, capability: GoogleCapability
    ) -> bool:
        return any(
            self.capability_availability(
                authority, capability, connection.connection_id
            ).available
            for connection in self._connections.list_google_connections_for_authority(
                authority
            )
        )

    def _connection(
        self, authority: ExecutionAuthority, connection_id: str | None
    ) -> GoogleConnection | None:
        return self._connections.get_google_connection_for_authority(
            authority, connection_id
        )

    def _load_connection_payload(
        self, authority: ExecutionAuthority, connection: GoogleConnection, key: str
    ) -> dict[str, object] | None:
        storage = self._storage(authority, connection.connection_id)
        payload = storage.get_sync(key, collection=_OAUTH_COLLECTION)
        if payload is not None or not connection.is_default:
            return payload
        legacy = EncryptedOAuthStorage(
            secrets=self._secrets,
            authority=authority,
            namespace=GOOGLE_OAUTH_NAMESPACE,
        )
        migrated = legacy.relocate_sync(
            key,
            destination=storage,
            collection=_OAUTH_COLLECTION,
        )
        if migrated:
            logger.info(
                "Legacy Google OAuth state migrated",
                data={
                    "event": "google_legacy_oauth_state_migrated",
                    "connection_id": connection.connection_id,
                    "record_kind": key,
                    "record_count": 1,
                },
            )
        return storage.get_sync(key, collection=_OAUTH_COLLECTION)

    def _delete_connection_keys(
        self,
        authority: ExecutionAuthority,
        connection: GoogleConnection,
        keys: tuple[str, ...],
    ) -> None:
        storage = self._storage(authority, connection.connection_id)
        legacy_storages = (
            (
                EncryptedOAuthStorage(
                    secrets=self._secrets,
                    authority=authority,
                    namespace=GOOGLE_OAUTH_NAMESPACE,
                ),
            )
            if connection.is_default
            else ()
        )
        deleted_count = storage.delete_many_sync(
            keys,
            collection=_OAUTH_COLLECTION,
            additional_storages=legacy_storages,
        )
        if legacy_storages:
            logger.info(
                "Google OAuth state cleanup completed",
                data={
                    "event": "google_legacy_oauth_cleanup_completed",
                    "connection_id": connection.connection_id,
                    "record_count": deleted_count,
                    "status": "completed",
                },
            )

    def _discard_stale_payload(
        self,
        authority: ExecutionAuthority,
        connection: GoogleConnection,
        key: str,
    ) -> None:
        try:
            self._storage(authority, connection.connection_id).delete_sync(
                key,
                collection=_OAUTH_COLLECTION,
            )
        except Exception as exc:
            logger.warning(
                "Stale Google OAuth state cleanup deferred",
                data={
                    "event": "google_oauth_stale_cleanup_deferred",
                    "connection_id": connection.connection_id,
                    "error_type": type(exc).__name__,
                },
            )

    def _storage(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> EncryptedOAuthStorage:
        return EncryptedOAuthStorage(
            secrets=self._secrets,
            authority=authority,
            namespace=f"{GOOGLE_OAUTH_NAMESPACE}.{connection_id}",
        )


def _status_not_configured() -> GoogleConnectionStatus:
    return GoogleConnectionStatus(
        connection_id=None,
        slug=None,
        display_name=None,
        is_default=False,
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
        connection_id=connection.connection_id,
        slug=connection.slug,
        display_name=connection.display_name,
        is_default=connection.is_default,
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


def _payload_matches_credential(
    payload: dict[str, object], credential: GoogleOAuthClientCredential
) -> bool:
    return (
        payload.get("oauth_generation") == credential.oauth_generation
        and payload.get("credential_id") == credential.credential_id
    )


def _token_payload(
    token_state: GoogleOAuthTokenState,
    credential: GoogleOAuthClientCredential,
) -> dict[str, object]:
    return {
        **asdict(token_state),
        "oauth_generation": credential.oauth_generation,
        "credential_id": credential.credential_id,
    }
