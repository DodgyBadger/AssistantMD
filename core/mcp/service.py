"""Authorization-aware management of MCP connection definitions."""

from __future__ import annotations

import json
import re
import secrets as random_secrets
import sqlite3
from collections.abc import Callable
from typing import cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from core.advanced_shell.authority import require_advanced_shell_authority
from core.advanced_shell.stdio import (
    MAX_ROOTS,
    encode_structured_launch,
    validate_advanced_shell_path,
    validate_arguments,
    validate_environment,
    validate_executable,
)
from core.identity import ExecutionAuthority, require_current_execution_authority
from core.logger import UnifiedLogger
from core.secrets import (
    EncryptedSecretsService,
    SecretCopy,
    SecretIdentity,
    SecretNamespaceDeletion,
    SecretWrite,
)

from .models import (
    MCPAuthMode,
    MCPConnection,
    MCPConnectionCreate,
    MCPConnectionUpdate,
    MCPStdioConfig,
    MCPTransport,
)
from .oauth_storage import MCP_OAUTH_FENCE_NAME, EncryptedMCPOAuthStorage
from .schema import connect_mcp, ensure_mcp_schema

MCP_SECRET_NAMESPACE_PREFIX = "mcp.connection."
MCP_CREDENTIAL_NAME = "credential"
MCP_OAUTH_CLIENT_SECRET_NAME = "oauth_client_secret"
MCP_MUTATION_NAMESPACE_PREFIX = "mcp.mutation."
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
logger = UnifiedLogger(tag="mcp-connection-mutations")


class MCPMutationUnavailableError(RuntimeError):
    """Raised when a durable connection mutation cannot currently converge."""


class MCPConnectionService:
    """Manage connection metadata and credentials under execution authority."""

    def __init__(
        self,
        *,
        system_root: str,
        secrets: EncryptedSecretsService,
        on_change: Callable[[str, str], None] | None = None,
        mutation_failpoint: Callable[[str, str], None] | None = None,
        advanced_shell_stdio_enabled: bool = False,
    ) -> None:
        self._system_root = system_root
        self._secrets = secrets
        self._on_change = on_change
        self._mutation_failpoint = mutation_failpoint
        self._advanced_shell_stdio_enabled = advanced_shell_stdio_enabled
        ensure_mcp_schema(system_root)

    def list_connections(self) -> list[MCPConnection]:
        """List sanitized connections owned by the current principal."""
        return self.list_connections_for_authority(
            require_current_execution_authority()
        )

    def get_connection(self, connection_id: str) -> MCPConnection | None:
        """Return a current-principal connection without revealing other owners."""
        return self.get_connection_for_authority(
            require_current_execution_authority(), connection_id
        )

    def create_connection(self, request: MCPConnectionCreate) -> MCPConnection:
        """Create a current-principal connection and optional encrypted credential."""
        return self.create_connection_for_authority(
            require_current_execution_authority(), request
        )

    def update_connection(
        self, connection_id: str, request: MCPConnectionUpdate
    ) -> MCPConnection:
        """Update mutable metadata while preserving immutable identity and slug."""
        authority = require_current_execution_authority()
        clean_id = _required_id(connection_id)
        self._reconcile_target(authority, clean_id)
        previous = self._require_for_authority(authority, clean_id)
        normalized = _normalize_update(request)
        self._require_supported_transport(normalized.transport)
        if normalized.transport is MCPTransport.ADVANCED_SHELL_STDIO:
            require_advanced_shell_authority(authority)
        delete_credential = normalized.auth_mode not in {
            MCPAuthMode.BEARER,
            MCPAuthMode.HEADER,
        }
        delete_oauth_client_secret = normalized.auth_mode is not MCPAuthMode.OAUTH
        delete_oauth_state = delete_oauth_client_secret or (
            previous.auth_mode is MCPAuthMode.OAUTH
            and (
                previous.url != normalized.url
                or previous.oauth_client_id != normalized.oauth_client_id
                or previous.oauth_scopes != normalized.oauth_scopes
            )
        )
        operation_id = str(uuid4())
        fence_token = random_secrets.token_hex(16) if delete_oauth_state else None
        payload = _mutation_payload(
            copies=(MCP_OAUTH_FENCE_NAME,) if fence_token else (),
            deletions=tuple(
                name
                for name, required in (
                    (MCP_CREDENTIAL_NAME, delete_credential),
                    (MCP_OAUTH_CLIENT_SECRET_NAME, delete_oauth_client_secret),
                )
                if required
            ),
            delete_oauth_state=delete_oauth_state,
        )
        if fence_token is not None:
            self._register_staging_mutation(
                authority,
                operation_id,
                clean_id,
                kind="update",
                payload=payload,
            )
            try:
                self._stage_values(
                    authority,
                    operation_id,
                    {MCP_OAUTH_FENCE_NAME: fence_token},
                )
                self._failpoint("after_stage", operation_id)
            except Exception:
                self._abandon_staging(authority, operation_id)
                raise
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE mcp_connections SET
                        display_name = ?, url = ?, transport = ?, auth_mode = ?,
                        header_name = ?, enabled = ?, allow_private_http = ?,
                        allowed_tools_json = ?,
                        oauth_client_id = ?, oauth_scopes_json = ?,
                        stdio_executable = ?, stdio_arguments_json = ?,
                        stdio_working_directory = ?, stdio_environment_json = ?,
                        stdio_roots_json = ?,
                        lifecycle_state = 'pending',
                        oauth_fence_token = COALESCE(?, oauth_fence_token),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_principal_id = ? AND connection_id = ?
                      AND lifecycle_state = 'active'
                    """,
                    (
                        normalized.display_name,
                        normalized.url,
                        normalized.transport.value,
                        normalized.auth_mode.value,
                        normalized.header_name,
                        int(normalized.enabled),
                        int(normalized.allow_private_http),
                        _dump_allowed_tools(normalized.allowed_tools),
                        normalized.oauth_client_id,
                        _dump_allowed_tools(normalized.oauth_scopes),
                        normalized.stdio.executable if normalized.stdio else None,
                        _dump_stdio_arguments(normalized.stdio),
                        (
                            normalized.stdio.working_directory
                            if normalized.stdio
                            else None
                        ),
                        _dump_stdio_environment(normalized.stdio),
                        _dump_stdio_roots(normalized.stdio),
                        fence_token,
                        authority.principal_id,
                        clean_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise LookupError("MCP connection not found.")
                if fence_token is None:
                    self._insert_mutation(
                        conn,
                        operation_id=operation_id,
                        authority=authority,
                        connection_id=clean_id,
                        kind="update",
                        payload=payload,
                    )
                else:
                    self._promote_staging_intent(conn, operation_id)
        except Exception:
            if fence_token is not None:
                self._abandon_staging(authority, operation_id)
            raise
        finally:
            conn.close()
        self._log_mutation_started(operation_id, clean_id, "update")
        self._failpoint("after_intent", operation_id)
        self._finish_new_mutation(operation_id)
        return self._require_for_authority(authority, clean_id)

    def set_credential(self, connection_id: str, credential: str) -> MCPConnection:
        """Create or replace the current-principal encrypted static credential."""
        authority = require_current_execution_authority()
        clean_id = _required_id(connection_id)
        self._reconcile_target(authority, clean_id)
        connection = self._require_for_authority(authority, clean_id)
        if connection.auth_mode not in {MCPAuthMode.BEARER, MCPAuthMode.HEADER}:
            raise ValueError("This MCP connection does not use a static credential.")
        value = str(credential or "").strip()
        if not value:
            raise ValueError("MCP credential cannot be empty.")
        self._start_staged_mutation(
            authority,
            clean_id,
            kind="set_credential",
            staged_values={MCP_CREDENTIAL_NAME: value},
        )
        return self._require_for_authority(authority, clean_id)

    def clear_credential(self, connection_id: str) -> MCPConnection:
        """Remove a current-principal static credential."""
        authority = require_current_execution_authority()
        clean_id = _required_id(connection_id)
        self._reconcile_target(authority, clean_id)
        connection = self._require_for_authority(authority, clean_id)
        if connection.transport is MCPTransport.ADVANCED_SHELL_STDIO:
            raise ValueError("Advanced-shell stdio connections do not use credentials.")
        self._start_simple_mutation(
            authority,
            clean_id,
            kind="clear_credential",
            payload=_mutation_payload(deletions=(MCP_CREDENTIAL_NAME,)),
        )
        return self._require_for_authority(authority, clean_id)

    def set_oauth_client_secret(
        self, connection_id: str, client_secret: str
    ) -> MCPConnection:
        """Create or replace a write-only OAuth client secret."""
        authority = require_current_execution_authority()
        clean_id = _required_id(connection_id)
        self._reconcile_target(authority, clean_id)
        connection = self._require_for_authority(authority, clean_id)
        if connection.auth_mode is not MCPAuthMode.OAUTH:
            raise ValueError("This MCP connection does not use OAuth.")
        value = str(client_secret or "").strip()
        if not value:
            raise ValueError("OAuth client secret cannot be empty.")
        self._start_staged_mutation(
            authority,
            clean_id,
            kind="set_oauth_client_secret",
            staged_values={
                MCP_OAUTH_CLIENT_SECRET_NAME: value,
                MCP_OAUTH_FENCE_NAME: random_secrets.token_hex(16),
            },
            delete_oauth_state=True,
        )
        return self._require_for_authority(authority, clean_id)

    def resolve_oauth_client_secret(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> str | None:
        """Resolve an OAuth client secret only after proving ownership."""
        self._require_for_authority(authority, connection_id)
        return self._secrets.get_for_authority(
            authority,
            _credential_namespace(connection_id),
            MCP_OAUTH_CLIENT_SECRET_NAME,
        )

    def disconnect_oauth(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> MCPConnection:
        """Fence OAuth writers and atomically clear durable OAuth state."""
        clean_id = _required_id(connection_id)
        self._reconcile_target(authority, clean_id)
        connection = self._require_for_authority(authority, clean_id)
        if connection.auth_mode is not MCPAuthMode.OAUTH:
            raise ValueError("This MCP connection does not use OAuth.")
        self._start_staged_mutation(
            authority,
            clean_id,
            kind="disconnect_oauth",
            staged_values={MCP_OAUTH_FENCE_NAME: random_secrets.token_hex(16)},
            delete_oauth_state=True,
        )
        return self._require_for_authority(authority, clean_id)

    def delete_connection(self, connection_id: str) -> None:
        """Delete a current-principal connection and its encrypted credential."""
        authority = require_current_execution_authority()
        clean_id = _required_id(connection_id)
        self._reconcile_target(authority, clean_id)
        self._require_for_authority(authority, clean_id)
        operation_id = str(uuid4())
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE mcp_connections SET lifecycle_state = 'deleting',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_principal_id = ? AND connection_id = ?
                      AND lifecycle_state = 'active'
                    """,
                    (authority.principal_id, clean_id),
                )
                if cursor.rowcount != 1:
                    raise LookupError("MCP connection not found.")
                self._insert_mutation(
                    conn,
                    operation_id=operation_id,
                    authority=authority,
                    connection_id=clean_id,
                    kind="delete",
                    payload=_mutation_payload(delete_connection_secrets=True),
                )
        finally:
            conn.close()
        self._log_mutation_started(operation_id, clean_id, "delete")
        self._failpoint("after_intent", operation_id)
        self._finish_new_mutation(operation_id)

    def get_connection_test_material(
        self, connection_id: str
    ) -> tuple[MCPConnection, str | None]:
        """Resolve one connection and credential under current authority."""
        authority = require_current_execution_authority()
        connection = self._require_for_authority(authority, connection_id)
        credential = self._secrets.get_for_authority(
            authority,
            _credential_namespace(connection_id),
            MCP_CREDENTIAL_NAME,
        )
        return connection, credential

    def list_connections_for_authority(
        self, authority: ExecutionAuthority
    ) -> list[MCPConnection]:
        """Trusted isolation helper for non-request execution and tests."""
        conn = connect_mcp(self._system_root)
        try:
            rows = conn.execute(
                """
                SELECT * FROM mcp_connections
                WHERE owner_principal_id = ? AND lifecycle_state = 'active'
                  AND NOT EXISTS (
                    SELECT 1 FROM mcp_connection_mutations mutations
                    WHERE mutations.owner_principal_id = mcp_connections.owner_principal_id
                      AND mutations.connection_id = mcp_connections.connection_id
                  )
                ORDER BY LOWER(display_name), connection_id
                """,
                (authority.principal_id,),
            ).fetchall()
        finally:
            conn.close()
        return [self._connection_from_row(authority, row) for row in rows]

    def get_connection_for_authority(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> MCPConnection | None:
        """Trusted lookup that still scopes the query by its explicit authority."""
        conn = connect_mcp(self._system_root)
        try:
            row = conn.execute(
                """
                SELECT * FROM mcp_connections
                WHERE owner_principal_id = ? AND connection_id = ?
                  AND lifecycle_state = 'active'
                  AND NOT EXISTS (
                    SELECT 1 FROM mcp_connection_mutations mutations
                    WHERE mutations.owner_principal_id = mcp_connections.owner_principal_id
                      AND mutations.connection_id = mcp_connections.connection_id
                  )
                """,
                (authority.principal_id, _required_id(connection_id)),
            ).fetchone()
        finally:
            conn.close()
        return self._connection_from_row(authority, row) if row is not None else None

    def create_connection_for_authority(
        self, authority: ExecutionAuthority, request: MCPConnectionCreate
    ) -> MCPConnection:
        """Trusted creation helper used to prove principal isolation."""
        normalized = _normalize_create(request)
        self._require_supported_transport(normalized.transport)
        if normalized.transport is MCPTransport.ADVANCED_SHELL_STDIO:
            require_advanced_shell_authority(authority)
        connection_id = str(uuid4())
        operation_id = str(uuid4())
        fence_token = random_secrets.token_hex(16)
        staged_values = {MCP_OAUTH_FENCE_NAME: fence_token}
        if normalized.credential is not None:
            staged_values[MCP_CREDENTIAL_NAME] = normalized.credential
        if normalized.oauth_client_secret is not None:
            staged_values[MCP_OAUTH_CLIENT_SECRET_NAME] = normalized.oauth_client_secret
        payload = _mutation_payload(copies=tuple(staged_values))
        self._register_staging_mutation(
            authority,
            operation_id,
            connection_id,
            kind="create",
            payload=payload,
        )
        try:
            self._stage_values(authority, operation_id, staged_values)
            self._failpoint("after_stage", operation_id)
        except Exception:
            self._abandon_staging(authority, operation_id)
            raise
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                slug = _unique_slug(conn, authority, normalized.display_name)
                conn.execute(
                    """
                    INSERT INTO mcp_connection_slugs (
                        connection_id, owner_principal_id, slug
                    ) VALUES (?, ?, ?)
                    """,
                    (connection_id, authority.principal_id, slug),
                )
                conn.execute(
                    """
                    INSERT INTO mcp_connections (
                        connection_id, owner_principal_id, slug, display_name,
                        url, transport, auth_mode, header_name, enabled,
                        allow_private_http, allowed_tools_json
                        , oauth_client_id, oauth_scopes_json,
                        stdio_executable, stdio_arguments_json,
                        stdio_working_directory, stdio_environment_json,
                        stdio_roots_json, lifecycle_state,
                        oauth_fence_token
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'pending', ?)
                    """,
                    (
                        connection_id,
                        authority.principal_id,
                        slug,
                        normalized.display_name,
                        normalized.url,
                        normalized.transport.value,
                        normalized.auth_mode.value,
                        normalized.header_name,
                        int(normalized.enabled),
                        int(normalized.allow_private_http),
                        _dump_allowed_tools(normalized.allowed_tools),
                        normalized.oauth_client_id,
                        _dump_allowed_tools(normalized.oauth_scopes),
                        normalized.stdio.executable if normalized.stdio else None,
                        _dump_stdio_arguments(normalized.stdio),
                        (
                            normalized.stdio.working_directory
                            if normalized.stdio
                            else None
                        ),
                        _dump_stdio_environment(normalized.stdio),
                        _dump_stdio_roots(normalized.stdio),
                        fence_token,
                    ),
                )
                self._promote_staging_intent(conn, operation_id)
        except Exception:
            self._abandon_staging(authority, operation_id)
            raise
        finally:
            conn.close()
        self._log_mutation_started(operation_id, connection_id, "create")
        self._failpoint("after_intent", operation_id)
        self._finish_new_mutation(operation_id)
        return self._require_for_authority(authority, connection_id)

    def _require_supported_transport(self, transport: MCPTransport) -> None:
        if (
            transport is MCPTransport.ADVANCED_SHELL_STDIO
            and not self._advanced_shell_stdio_enabled
        ):
            raise ValueError("Advanced-shell stdio requires advanced execution mode.")

    def resolve_credential(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> str | None:
        """Resolve a credential only after proving matching connection ownership."""
        self._require_for_authority(authority, connection_id)
        return self._secrets.get_for_authority(
            authority,
            _credential_namespace(connection_id),
            MCP_CREDENTIAL_NAME,
        )

    def oauth_storage(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> EncryptedMCPOAuthStorage:
        """Return encrypted OAuth storage after proving connection ownership."""
        self._require_for_authority(authority, connection_id)
        return EncryptedMCPOAuthStorage(
            secrets=self._secrets,
            authority=authority,
            connection_id=connection_id,
            fence_token=self._oauth_fence_token(authority, connection_id),
        )

    def reconcile_pending_mutations(self) -> int:
        """Converge every durable MCP mutation before runtime acquisition."""
        conn = connect_mcp(self._system_root)
        try:
            operation_ids = [
                str(row["operation_id"])
                for row in conn.execute(
                    """
                    SELECT operation_id FROM mcp_connection_mutations
                    ORDER BY created_at, operation_id
                    """
                ).fetchall()
            ]
        finally:
            conn.close()
        for operation_id in operation_ids:
            try:
                self._reconcile_operation(operation_id)
            except Exception:
                continue
        self._ensure_active_fences()
        return len(operation_ids)

    def _start_staged_mutation(
        self,
        authority: ExecutionAuthority,
        connection_id: str,
        *,
        kind: str,
        staged_values: dict[str, str],
        delete_oauth_state: bool = False,
    ) -> None:
        operation_id = str(uuid4())
        payload = _mutation_payload(
            copies=tuple(staged_values),
            delete_oauth_state=delete_oauth_state,
        )
        self._register_staging_mutation(
            authority,
            operation_id,
            connection_id,
            kind=kind,
            payload=payload,
        )
        try:
            self._stage_values(authority, operation_id, staged_values)
            self._failpoint("after_stage", operation_id)
            conn = connect_mcp(self._system_root)
            try:
                with conn:
                    fence_token = staged_values.get(MCP_OAUTH_FENCE_NAME)
                    cursor = conn.execute(
                        """
                        UPDATE mcp_connections SET lifecycle_state = 'pending',
                            oauth_fence_token = COALESCE(?, oauth_fence_token),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE owner_principal_id = ? AND connection_id = ?
                          AND lifecycle_state = 'active'
                        """,
                        (fence_token, authority.principal_id, connection_id),
                    )
                    if cursor.rowcount != 1:
                        raise LookupError("MCP connection not found.")
                    self._promote_staging_intent(conn, operation_id)
            finally:
                conn.close()
        except Exception:
            self._abandon_staging(authority, operation_id)
            raise
        self._log_mutation_started(operation_id, connection_id, kind)
        self._failpoint("after_intent", operation_id)
        self._finish_new_mutation(operation_id)

    def _start_simple_mutation(
        self,
        authority: ExecutionAuthority,
        connection_id: str,
        *,
        kind: str,
        payload: str,
    ) -> None:
        operation_id = str(uuid4())
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE mcp_connections SET lifecycle_state = 'pending',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_principal_id = ? AND connection_id = ?
                      AND lifecycle_state = 'active'
                    """,
                    (authority.principal_id, connection_id),
                )
                if cursor.rowcount != 1:
                    raise LookupError("MCP connection not found.")
                self._insert_mutation(
                    conn,
                    operation_id=operation_id,
                    authority=authority,
                    connection_id=connection_id,
                    kind=kind,
                    payload=payload,
                )
        finally:
            conn.close()
        self._log_mutation_started(operation_id, connection_id, kind)
        self._failpoint("after_intent", operation_id)
        self._finish_new_mutation(operation_id)

    @staticmethod
    def _insert_mutation(
        conn: sqlite3.Connection,
        *,
        operation_id: str,
        authority: ExecutionAuthority,
        connection_id: str,
        kind: str,
        payload: str,
        state: str = "intent",
    ) -> None:
        conn.execute(
            """
            INSERT INTO mcp_connection_mutations (
                operation_id, owner_principal_id, connection_id,
                mutation_kind, payload_json, state
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                authority.principal_id,
                connection_id,
                kind,
                payload,
                state,
            ),
        )

    def _register_staging_mutation(
        self,
        authority: ExecutionAuthority,
        operation_id: str,
        connection_id: str,
        *,
        kind: str,
        payload: str,
    ) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                self._insert_mutation(
                    conn,
                    operation_id=operation_id,
                    authority=authority,
                    connection_id=connection_id,
                    kind=kind,
                    payload=payload,
                    state="staging",
                )
        finally:
            conn.close()

    @staticmethod
    def _promote_staging_intent(conn: sqlite3.Connection, operation_id: str) -> None:
        cursor = conn.execute(
            """
            UPDATE mcp_connection_mutations SET state = 'intent',
                updated_at = CURRENT_TIMESTAMP
            WHERE operation_id = ? AND state = 'staging'
            """,
            (operation_id,),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("MCP mutation staging record is unavailable.")

    def _stage_values(
        self,
        authority: ExecutionAuthority,
        operation_id: str,
        values: dict[str, str],
    ) -> None:
        self._secrets.set_many_for_authorities(
            [
                SecretWrite(
                    authority=authority,
                    namespace=_mutation_namespace(operation_id),
                    name=name,
                    value=value,
                )
                for name, value in values.items()
            ]
        )

    def _reconcile_target(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        conn = connect_mcp(self._system_root)
        try:
            row = conn.execute(
                """
                SELECT operation_id FROM mcp_connection_mutations
                WHERE owner_principal_id = ? AND connection_id = ?
                """,
                (authority.principal_id, connection_id),
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            try:
                self._reconcile_operation(str(row["operation_id"]))
            except Exception as exc:
                raise MCPMutationUnavailableError(
                    "MCP connection configuration is temporarily unavailable."
                ) from exc

    def _finish_new_mutation(self, operation_id: str) -> None:
        try:
            self._reconcile_operation(operation_id)
        except Exception as exc:
            raise MCPMutationUnavailableError(
                "MCP connection configuration is temporarily unavailable."
            ) from exc

    def _reconcile_operation(self, operation_id: str) -> None:
        try:
            while True:
                mutation = self._mutation_row(operation_id)
                if mutation is None:
                    return
                authority = ExecutionAuthority(str(mutation["owner_principal_id"]))
                connection_id = str(mutation["connection_id"])
                state = str(mutation["state"])
                payload = _parse_mutation_payload(str(mutation["payload_json"]))
                if state == "staging":
                    self._cleanup_pre_intent(authority, operation_id)
                    self._delete_mutation(operation_id)
                    return
                if state == "intent":
                    self._apply_secret_effects(
                        authority,
                        operation_id,
                        connection_id,
                        payload,
                    )
                    self._failpoint("after_secret_effects", operation_id)
                    self._advance_mutation_state(
                        operation_id, expected="intent", desired="secrets_applied"
                    )
                    self._failpoint("after_secrets_applied", operation_id)
                    continue
                if state == "secrets_applied":
                    self._finalize_metadata(
                        operation_id=operation_id,
                        authority=authority,
                        connection_id=connection_id,
                        kind=str(mutation["mutation_kind"]),
                    )
                    self._failpoint("after_finalize", operation_id)
                    continue
                if state == "finalized":
                    self._cleanup_pre_intent(authority, operation_id)
                    self._dispatch_finalized_mutation(
                        operation_id=operation_id,
                        authority=authority,
                        connection_id=connection_id,
                        mutation_kind=str(mutation["mutation_kind"]),
                    )
                    return
                raise RuntimeError("Stored MCP mutation state is invalid.")
        except Exception as exc:
            self._record_mutation_failure(operation_id, exc)
            raise

    def _apply_secret_effects(
        self,
        authority: ExecutionAuthority,
        operation_id: str,
        connection_id: str,
        payload: dict[str, object],
    ) -> None:
        copies = tuple(
            SecretCopy(
                source=SecretIdentity(_mutation_namespace(operation_id), name),
                destination=SecretIdentity(_credential_namespace(connection_id), name),
                overwrite=True,
            )
            for name in _payload_names(payload, "copies")
        )
        deletions = tuple(
            SecretIdentity(_credential_namespace(connection_id), name)
            for name in _payload_names(payload, "deletions")
        )
        namespace_deletions: list[SecretNamespaceDeletion] = []
        if payload["delete_oauth_state"] is True:
            namespace_deletions.append(
                SecretNamespaceDeletion(_oauth_namespace(connection_id))
            )
        if payload["delete_connection_secrets"] is True:
            namespace_deletions.extend(
                (
                    SecretNamespaceDeletion(_credential_namespace(connection_id)),
                    SecretNamespaceDeletion(_oauth_namespace(connection_id)),
                )
            )
        self._secrets.mutate_for_authority(
            authority,
            copies=copies,
            deletions=deletions,
            namespace_deletions=tuple(namespace_deletions),
        )

    def _finalize_metadata(
        self,
        *,
        operation_id: str,
        authority: ExecutionAuthority,
        connection_id: str,
        kind: str,
    ) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                claim = conn.execute(
                    """
                    UPDATE mcp_connection_mutations SET updated_at = updated_at
                    WHERE operation_id = ? AND state = 'secrets_applied'
                    """,
                    (operation_id,),
                )
                if claim.rowcount != 1:
                    return
                if kind == "delete":
                    conn.execute(
                        """
                        DELETE FROM mcp_connections
                        WHERE owner_principal_id = ? AND connection_id = ?
                        """,
                        (authority.principal_id, connection_id),
                    )
                else:
                    version_expression = (
                        "config_version" if kind == "create" else "config_version + 1"
                    )
                    cursor = conn.execute(
                        f"""
                        UPDATE mcp_connections SET lifecycle_state = 'active',
                            config_version = {version_expression},
                            updated_at = CURRENT_TIMESTAMP
                        WHERE owner_principal_id = ? AND connection_id = ?
                          AND lifecycle_state = 'pending'
                        """,
                        (authority.principal_id, connection_id),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            "Pending MCP connection metadata is missing."
                        )
                conn.execute(
                    """
                    UPDATE mcp_connection_mutations SET state = 'finalized',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE operation_id = ? AND state = 'secrets_applied'
                    """,
                    (operation_id,),
                )
        finally:
            conn.close()

    def _advance_mutation_state(
        self, operation_id: str, *, expected: str, desired: str
    ) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE mcp_connection_mutations SET state = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE operation_id = ? AND state = ?
                    """,
                    (desired, operation_id, expected),
                )
        finally:
            conn.close()

    def _mutation_row(self, operation_id: str) -> sqlite3.Row | None:
        conn = connect_mcp(self._system_root)
        try:
            return cast(
                sqlite3.Row | None,
                conn.execute(
                    """
                SELECT * FROM mcp_connection_mutations WHERE operation_id = ?
                """,
                    (operation_id,),
                ).fetchone(),
            )
        finally:
            conn.close()

    def _delete_mutation(self, operation_id: str) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                conn.execute(
                    "DELETE FROM mcp_connection_mutations WHERE operation_id = ?",
                    (operation_id,),
                )
        finally:
            conn.close()

    def _dispatch_finalized_mutation(
        self,
        *,
        operation_id: str,
        authority: ExecutionAuthority,
        connection_id: str,
        mutation_kind: str,
    ) -> None:
        """Serialize terminal effects while retaining rollback-safe retry evidence."""
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT 1 FROM mcp_connection_mutations
                    WHERE operation_id = ? AND state = 'finalized'
                    """,
                    (operation_id,),
                ).fetchone()
                if row is None:
                    return
                self._notify(authority, connection_id)
                self._failpoint("after_notify", operation_id)
                logger.info(
                    "MCP connection mutation completed",
                    data={
                        "event": "mcp_connection_mutation_completed",
                        "operation_id": operation_id,
                        "connection_id": connection_id,
                        "mutation_kind": mutation_kind,
                    },
                )
                self._failpoint("after_terminal_log", operation_id)
                conn.execute(
                    "DELETE FROM mcp_connection_mutations WHERE operation_id = ?",
                    (operation_id,),
                )
        finally:
            conn.close()

    def _record_mutation_failure(self, operation_id: str, exc: Exception) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE mcp_connection_mutations
                    SET attempt_count = attempt_count + 1,
                        last_error_class = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE operation_id = ?
                    """,
                    (type(exc).__name__[:120], operation_id),
                )
        finally:
            conn.close()
        logger.warning(
            "MCP connection mutation retry failed",
            data={
                "event": "mcp_connection_mutation_retry_failed",
                "operation_id": operation_id,
                "error_class": type(exc).__name__[:120],
            },
        )

    def _cleanup_pre_intent(
        self, authority: ExecutionAuthority, operation_id: str
    ) -> None:
        self._secrets.mutate_for_authority(
            authority,
            namespace_deletions=(
                SecretNamespaceDeletion(_mutation_namespace(operation_id)),
            ),
        )

    def _abandon_staging(
        self, authority: ExecutionAuthority, operation_id: str
    ) -> None:
        self._cleanup_pre_intent(authority, operation_id)
        self._delete_mutation(operation_id)

    def _ensure_active_fences(self) -> None:
        conn = connect_mcp(self._system_root)
        try:
            rows = conn.execute(
                """
                SELECT owner_principal_id, connection_id, oauth_fence_token
                FROM mcp_connections WHERE lifecycle_state = 'active'
                """
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            authority = ExecutionAuthority(str(row["owner_principal_id"]))
            connection_id = str(row["connection_id"])
            namespace = _credential_namespace(connection_id)
            if (
                self._secrets.get_for_authority(
                    authority, namespace, MCP_OAUTH_FENCE_NAME
                )
                is None
            ):
                self._secrets.set_for_authority(
                    authority,
                    namespace,
                    MCP_OAUTH_FENCE_NAME,
                    str(row["oauth_fence_token"]),
                )

    def _failpoint(self, boundary: str, operation_id: str) -> None:
        if self._mutation_failpoint is not None:
            self._mutation_failpoint(boundary, operation_id)

    @staticmethod
    def _log_mutation_started(
        operation_id: str, connection_id: str, mutation_kind: str
    ) -> None:
        logger.info(
            "MCP connection mutation started",
            data={
                "event": "mcp_connection_mutation_started",
                "operation_id": operation_id,
                "connection_id": connection_id,
                "mutation_kind": mutation_kind,
            },
        )

    def _oauth_fence_token(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> str:
        conn = connect_mcp(self._system_root)
        try:
            row = conn.execute(
                """
                SELECT oauth_fence_token FROM mcp_connections
                WHERE owner_principal_id = ? AND connection_id = ?
                  AND lifecycle_state = 'active'
                  AND NOT EXISTS (
                    SELECT 1 FROM mcp_connection_mutations mutations
                    WHERE mutations.owner_principal_id = mcp_connections.owner_principal_id
                      AND mutations.connection_id = mcp_connections.connection_id
                  )
                """,
                (authority.principal_id, _required_id(connection_id)),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise LookupError("MCP connection not found.")
        return str(row["oauth_fence_token"])

    def _connection_from_row(
        self, authority: ExecutionAuthority, row: sqlite3.Row
    ) -> MCPConnection:
        values = dict(row)
        connection_id = str(values["connection_id"])
        credential_present = bool(
            self._secrets.get_for_authority(
                authority,
                _credential_namespace(connection_id),
                MCP_CREDENTIAL_NAME,
            )
        )
        oauth_client_secret_present = bool(
            self._secrets.get_for_authority(
                authority,
                _credential_namespace(connection_id),
                MCP_OAUTH_CLIENT_SECRET_NAME,
            )
        )
        return MCPConnection(
            connection_id=connection_id,
            slug=str(values["slug"]),
            display_name=str(values["display_name"]),
            url=str(values["url"]) if values["url"] else None,
            transport=MCPTransport(str(values["transport"])),
            auth_mode=MCPAuthMode(str(values["auth_mode"])),
            header_name=str(values["header_name"]) if values["header_name"] else None,
            enabled=bool(values["enabled"]),
            allow_private_http=bool(values["allow_private_http"]),
            allowed_tools=_load_allowed_tools(values["allowed_tools_json"]),
            credential_present=credential_present,
            oauth_client_id=(
                str(values["oauth_client_id"]) if values["oauth_client_id"] else None
            ),
            oauth_client_secret_present=oauth_client_secret_present,
            oauth_scopes=_load_allowed_tools(values["oauth_scopes_json"]),
            config_version=int(values["config_version"]),
            created_at=str(values["created_at"]),
            updated_at=str(values["updated_at"]),
            stdio=_load_stdio_config(values),
        )

    def _require_for_authority(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> MCPConnection:
        connection = self.get_connection_for_authority(authority, connection_id)
        if connection is None:
            raise LookupError("MCP connection not found.")
        return connection

    def _notify(self, authority: ExecutionAuthority, connection_id: str) -> None:
        if self._on_change is not None:
            self._on_change(authority.principal_id, connection_id)


def _normalize_create(request: MCPConnectionCreate) -> MCPConnectionCreate:
    update = _normalize_update(
        MCPConnectionUpdate(
            display_name=request.display_name,
            url=request.url,
            transport=request.transport,
            auth_mode=request.auth_mode,
            header_name=request.header_name,
            enabled=request.enabled,
            allow_private_http=request.allow_private_http,
            allowed_tools=request.allowed_tools,
            oauth_client_id=request.oauth_client_id,
            oauth_scopes=request.oauth_scopes,
            stdio=request.stdio,
        )
    )
    credential = str(request.credential or "").strip() or None
    oauth_client_secret = str(request.oauth_client_secret or "").strip() or None
    if credential is not None and update.auth_mode not in {
        MCPAuthMode.BEARER,
        MCPAuthMode.HEADER,
    }:
        raise ValueError("Credentials are supported only for bearer or header auth.")
    if oauth_client_secret is not None and update.auth_mode is not MCPAuthMode.OAUTH:
        raise ValueError("OAuth client secrets are supported only for OAuth auth.")
    return MCPConnectionCreate(
        display_name=update.display_name,
        url=update.url,
        transport=update.transport,
        auth_mode=update.auth_mode,
        header_name=update.header_name,
        enabled=update.enabled,
        allow_private_http=update.allow_private_http,
        allowed_tools=update.allowed_tools,
        credential=credential,
        oauth_client_id=update.oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_scopes=update.oauth_scopes,
        stdio=update.stdio,
    )


def _normalize_update(request: MCPConnectionUpdate) -> MCPConnectionUpdate:
    display_name = str(request.display_name or "").strip()
    if not display_name or len(display_name) > 120:
        raise ValueError("MCP display name must contain 1 to 120 characters.")
    transport = MCPTransport(request.transport)
    stdio = _normalize_stdio(request.stdio)
    url = (
        None
        if transport is MCPTransport.ADVANCED_SHELL_STDIO
        else _sanitize_url(request.url)
    )
    auth_mode = MCPAuthMode(request.auth_mode)
    header_name = str(request.header_name or "").strip() or None
    if auth_mode is MCPAuthMode.HEADER:
        if header_name is None or not _HEADER_NAME_PATTERN.fullmatch(header_name):
            raise ValueError("Header auth requires a valid HTTP header name.")
    elif header_name is not None:
        raise ValueError("Header name is valid only for header auth.")
    allowed_tools = _normalize_allowed_tools(request.allowed_tools)
    oauth_client_id = str(request.oauth_client_id or "").strip() or None
    oauth_scopes = _normalize_allowed_tools(request.oauth_scopes)
    if auth_mode is not MCPAuthMode.OAUTH and (oauth_client_id or oauth_scopes):
        raise ValueError("OAuth client settings are valid only for OAuth auth.")
    if transport is MCPTransport.ADVANCED_SHELL_STDIO:
        if auth_mode is not MCPAuthMode.NONE or header_name is not None:
            raise ValueError(
                "Advanced-shell stdio connections do not support authentication."
            )
        if request.allow_private_http or oauth_client_id or oauth_scopes:
            raise ValueError(
                "HTTP and OAuth settings are invalid for advanced-shell stdio."
            )
        if stdio is None:
            raise ValueError("Advanced-shell stdio launch configuration is required.")
    elif stdio is not None:
        raise ValueError(
            "Advanced-shell stdio configuration requires advanced_shell_stdio transport."
        )
    return MCPConnectionUpdate(
        display_name=display_name,
        url=url,
        transport=transport,
        auth_mode=auth_mode,
        header_name=header_name,
        enabled=bool(request.enabled),
        allow_private_http=bool(request.allow_private_http),
        allowed_tools=allowed_tools,
        oauth_client_id=oauth_client_id,
        oauth_scopes=oauth_scopes,
        stdio=stdio,
    )


def _normalize_stdio(value: MCPStdioConfig | None) -> MCPStdioConfig | None:
    if value is None:
        return None
    arguments = validate_arguments(tuple(str(item) for item in value.arguments))
    environment = validate_environment(
        tuple((str(name), str(item)) for name, item in value.environment)
    )
    roots = tuple(
        validate_advanced_shell_path(root, label="Root") for root in value.roots
    )
    if len(roots) > MAX_ROOTS:
        raise ValueError("Advanced-shell stdio has too many Roots.")
    normalized = MCPStdioConfig(
        executable=validate_executable(value.executable),
        arguments=arguments,
        working_directory=validate_advanced_shell_path(
            value.working_directory, label="working directory"
        ),
        environment=environment,
        roots=roots,
    )
    encode_structured_launch(
        executable=normalized.executable,
        arguments=normalized.arguments,
        working_directory=normalized.working_directory,
        environment=normalized.environment,
    )
    return normalized


def _sanitize_url(value: str | None) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("MCP URL must be an absolute HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("MCP URL cannot contain credentials.")
    if parsed.query:
        raise ValueError(
            "MCP URL cannot contain query parameters; configure credentials separately."
        )
    if parsed.fragment:
        raise ValueError("MCP URL cannot contain a fragment.")
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", "", "")
    )


def _normalize_allowed_tools(values: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    normalized = tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )
    if not normalized:
        return None
    if len(normalized) > 200 or any(len(value) > 128 for value in normalized):
        raise ValueError("MCP allowed-tools policy exceeds supported limits.")
    return normalized


def _unique_slug(
    conn: sqlite3.Connection, authority: ExecutionAuthority, display_name: str
) -> str:
    base = _SLUG_PATTERN.sub("-", display_name.lower()).strip("-")[:48] or "mcp"
    candidate = base
    suffix = 2
    while conn.execute(
        "SELECT 1 FROM mcp_connection_slugs WHERE owner_principal_id = ? AND slug = ?",
        (authority.principal_id, candidate),
    ).fetchone():
        suffix_text = f"-{suffix}"
        candidate = f"{base[: 48 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return candidate


def _credential_namespace(connection_id: str) -> str:
    return f"{MCP_SECRET_NAMESPACE_PREFIX}{_required_id(connection_id)}"


def _oauth_namespace(connection_id: str) -> str:
    return f"{_credential_namespace(connection_id)}.oauth"


def _mutation_namespace(operation_id: str) -> str:
    return f"{MCP_MUTATION_NAMESPACE_PREFIX}{_required_id(operation_id)}"


def _required_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("MCP connection ID is required.")
    return normalized


def _dump_allowed_tools(values: tuple[str, ...] | None) -> str | None:
    return json.dumps(list(values), separators=(",", ":")) if values else None


def _load_allowed_tools(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    payload = json.loads(str(value))
    if not isinstance(payload, list) or not all(
        isinstance(item, str) for item in payload
    ):
        raise ValueError("Stored MCP allowed-tools policy is invalid.")
    return tuple(payload) or None


def _dump_stdio_arguments(value: MCPStdioConfig | None) -> str | None:
    return json.dumps(list(value.arguments), separators=(",", ":")) if value else None


def _dump_stdio_environment(value: MCPStdioConfig | None) -> str | None:
    return json.dumps(dict(value.environment), separators=(",", ":")) if value else None


def _dump_stdio_roots(value: MCPStdioConfig | None) -> str | None:
    return json.dumps(list(value.roots), separators=(",", ":")) if value else None


def _load_json_strings(value: object, *, label: str) -> tuple[str, ...]:
    payload = json.loads(str(value))
    if not isinstance(payload, list) or not all(
        isinstance(item, str) for item in payload
    ):
        raise ValueError(f"Stored advanced-shell stdio {label} is invalid.")
    return tuple(payload)


def _load_stdio_config(values: dict[str, object]) -> MCPStdioConfig | None:
    executable = values.get("stdio_executable")
    if executable is None:
        return None
    environment_payload = json.loads(str(values["stdio_environment_json"]))
    if not isinstance(environment_payload, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in environment_payload.items()
    ):
        raise ValueError("Stored advanced-shell stdio environment is invalid.")
    return _normalize_stdio(
        MCPStdioConfig(
            executable=str(executable),
            arguments=_load_json_strings(
                values["stdio_arguments_json"], label="arguments"
            ),
            working_directory=str(values["stdio_working_directory"]),
            environment=tuple(environment_payload.items()),
            roots=_load_json_strings(values["stdio_roots_json"], label="Roots"),
        )
    )


def _mutation_payload(
    *,
    copies: tuple[str, ...] = (),
    deletions: tuple[str, ...] = (),
    delete_oauth_state: bool = False,
    delete_connection_secrets: bool = False,
) -> str:
    allowed_names = {
        MCP_CREDENTIAL_NAME,
        MCP_OAUTH_CLIENT_SECRET_NAME,
        MCP_OAUTH_FENCE_NAME,
    }
    if not set(copies).union(deletions).issubset(allowed_names):
        raise ValueError("MCP mutation contains an unsupported secret identity.")
    return json.dumps(
        {
            "version": 1,
            "copies": list(copies),
            "deletions": list(deletions),
            "delete_oauth_state": delete_oauth_state,
            "delete_connection_secrets": delete_connection_secrets,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _parse_mutation_payload(value: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Stored MCP mutation payload is invalid.") from exc
    expected_keys = {
        "version",
        "copies",
        "deletions",
        "delete_oauth_state",
        "delete_connection_secrets",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise RuntimeError("Stored MCP mutation payload is invalid.")
    if payload["version"] != 1:
        raise RuntimeError("Stored MCP mutation payload version is unsupported.")
    for key in ("copies", "deletions"):
        names = payload[key]
        if (
            not isinstance(names, list)
            or not all(isinstance(name, str) for name in names)
            or len(set(names)) != len(names)
        ):
            raise RuntimeError("Stored MCP mutation payload is invalid.")
        allowed_names = {
            MCP_CREDENTIAL_NAME,
            MCP_OAUTH_CLIENT_SECRET_NAME,
            MCP_OAUTH_FENCE_NAME,
        }
        if not set(names).issubset(allowed_names):
            raise RuntimeError("Stored MCP mutation payload is invalid.")
    if not isinstance(payload["delete_oauth_state"], bool) or not isinstance(
        payload["delete_connection_secrets"], bool
    ):
        raise RuntimeError("Stored MCP mutation payload is invalid.")
    return payload


def _payload_names(payload: dict[str, object], key: str) -> tuple[str, ...]:
    values = payload[key]
    if not isinstance(values, list):
        raise RuntimeError("Stored MCP mutation payload is invalid.")
    return tuple(str(value) for value in values)
