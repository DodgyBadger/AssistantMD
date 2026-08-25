"""Authorization-aware management of MCP connection definitions."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from core.identity import ExecutionAuthority, require_current_execution_authority
from core.secrets import EncryptedSecretsService

from .models import (
    MCPAuthMode,
    MCPConnection,
    MCPConnectionCreate,
    MCPConnectionUpdate,
    MCPTransport,
)
from .oauth_storage import EncryptedMCPOAuthStorage
from .schema import connect_mcp, ensure_mcp_schema

MCP_SECRET_NAMESPACE_PREFIX = "mcp.connection."
MCP_CREDENTIAL_NAME = "credential"
MCP_OAUTH_CLIENT_SECRET_NAME = "oauth_client_secret"
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class MCPConnectionService:
    """Manage connection metadata and credentials under execution authority."""

    def __init__(
        self,
        *,
        system_root: str,
        secrets: EncryptedSecretsService,
        on_change: Callable[[str, str], None] | None = None,
    ) -> None:
        self._system_root = system_root
        self._secrets = secrets
        self._on_change = on_change
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
        previous = self._require_for_authority(authority, connection_id)
        normalized = _normalize_update(request)
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE mcp_connections SET
                        display_name = ?, url = ?, transport = ?, auth_mode = ?,
                        header_name = ?, enabled = ?, allowed_tools_json = ?,
                        oauth_client_id = ?, oauth_scopes_json = ?,
                        config_version = config_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (
                        normalized.display_name,
                        normalized.url,
                        normalized.transport.value,
                        normalized.auth_mode.value,
                        normalized.header_name,
                        int(normalized.enabled),
                        _dump_allowed_tools(normalized.allowed_tools),
                        normalized.oauth_client_id,
                        _dump_allowed_tools(normalized.oauth_scopes),
                        authority.principal_id,
                        _required_id(connection_id),
                    ),
                )
                if cursor.rowcount == 0:
                    raise LookupError("MCP connection not found.")
        finally:
            conn.close()
        if normalized.auth_mode not in {MCPAuthMode.BEARER, MCPAuthMode.HEADER}:
            self._delete_credential(authority, connection_id)
        if normalized.auth_mode is not MCPAuthMode.OAUTH:
            self._delete_oauth_state(authority, connection_id)
            self._delete_oauth_client_secret(authority, connection_id)
        elif previous.auth_mode is MCPAuthMode.OAUTH and (
            previous.url != normalized.url
            or previous.oauth_client_id != normalized.oauth_client_id
            or previous.oauth_scopes != normalized.oauth_scopes
        ):
            self._delete_oauth_state(authority, connection_id)
        self._notify(authority, connection_id)
        return self._require_for_authority(authority, connection_id)

    def set_credential(self, connection_id: str, credential: str) -> MCPConnection:
        """Create or replace the current-principal encrypted static credential."""
        authority = require_current_execution_authority()
        connection = self._require_for_authority(authority, connection_id)
        if connection.auth_mode not in {MCPAuthMode.BEARER, MCPAuthMode.HEADER}:
            raise ValueError("This MCP connection does not use a static credential.")
        value = str(credential or "").strip()
        if not value:
            raise ValueError("MCP credential cannot be empty.")
        self._secrets.set_for_authority(
            authority,
            _credential_namespace(connection_id),
            MCP_CREDENTIAL_NAME,
            value,
        )
        self._bump_version(authority, connection_id)
        return self._require_for_authority(authority, connection_id)

    def clear_credential(self, connection_id: str) -> MCPConnection:
        """Remove a current-principal static credential."""
        authority = require_current_execution_authority()
        self._require_for_authority(authority, connection_id)
        self._delete_credential(authority, connection_id)
        self._bump_version(authority, connection_id)
        return self._require_for_authority(authority, connection_id)

    def set_oauth_client_secret(
        self, connection_id: str, client_secret: str
    ) -> MCPConnection:
        """Create or replace a write-only OAuth client secret."""
        authority = require_current_execution_authority()
        connection = self._require_for_authority(authority, connection_id)
        if connection.auth_mode is not MCPAuthMode.OAUTH:
            raise ValueError("This MCP connection does not use OAuth.")
        value = str(client_secret or "").strip()
        if not value:
            raise ValueError("OAuth client secret cannot be empty.")
        self._delete_oauth_state(authority, connection_id)
        self._secrets.set_for_authority(
            authority,
            _credential_namespace(connection_id),
            MCP_OAUTH_CLIENT_SECRET_NAME,
            value,
        )
        self._bump_version(authority, connection_id)
        return self._require_for_authority(authority, connection_id)

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

    def delete_connection(self, connection_id: str) -> None:
        """Delete a current-principal connection and its encrypted credential."""
        authority = require_current_execution_authority()
        clean_id = _required_id(connection_id)
        self._require_for_authority(authority, clean_id)
        self._delete_credential(authority, clean_id)
        self._delete_oauth_client_secret(authority, clean_id)
        self._delete_oauth_state(authority, clean_id)
        self._delete_connection_row(authority, clean_id)
        self._notify(authority, clean_id)

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
                WHERE owner_principal_id = ?
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
        connection_id = str(uuid4())
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
                        allowed_tools_json
                        , oauth_client_id, oauth_scopes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        _dump_allowed_tools(normalized.allowed_tools),
                        normalized.oauth_client_id,
                        _dump_allowed_tools(normalized.oauth_scopes),
                    ),
                )
        finally:
            conn.close()
        if normalized.credential is not None:
            try:
                self._secrets.set_for_authority(
                    authority,
                    _credential_namespace(connection_id),
                    MCP_CREDENTIAL_NAME,
                    normalized.credential,
                )
            except Exception:
                self._delete_credential(authority, connection_id)
                self._delete_oauth_client_secret(authority, connection_id)
                self._rollback_connection_create(authority, connection_id)
                raise
        if normalized.oauth_client_secret is not None:
            try:
                self._secrets.set_for_authority(
                    authority,
                    _credential_namespace(connection_id),
                    MCP_OAUTH_CLIENT_SECRET_NAME,
                    normalized.oauth_client_secret,
                )
            except Exception:
                self._delete_credential(authority, connection_id)
                self._delete_oauth_client_secret(authority, connection_id)
                self._rollback_connection_create(authority, connection_id)
                raise
        self._notify(authority, connection_id)
        return self._require_for_authority(authority, connection_id)

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
        )

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
            url=str(values["url"]),
            transport=MCPTransport(str(values["transport"])),
            auth_mode=MCPAuthMode(str(values["auth_mode"])),
            header_name=str(values["header_name"]) if values["header_name"] else None,
            enabled=bool(values["enabled"]),
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
        )

    def _require_for_authority(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> MCPConnection:
        connection = self.get_connection_for_authority(authority, connection_id)
        if connection is None:
            raise LookupError("MCP connection not found.")
        return connection

    def _delete_credential(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        self._secrets.delete_for_authority(
            authority,
            _credential_namespace(connection_id),
            MCP_CREDENTIAL_NAME,
        )

    def _delete_oauth_client_secret(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        self._secrets.delete_for_authority(
            authority,
            _credential_namespace(connection_id),
            MCP_OAUTH_CLIENT_SECRET_NAME,
        )

    def _delete_oauth_state(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        namespace = f"{_credential_namespace(connection_id)}.oauth"
        for item in self._secrets.list_metadata_for_authority(authority, namespace):
            self._secrets.delete_for_authority(authority, namespace, item.name)

    def _delete_connection_row(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                conn.execute(
                    """
                    DELETE FROM mcp_connections
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (authority.principal_id, connection_id),
                )
        finally:
            conn.close()

    def _rollback_connection_create(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                conn.execute(
                    """
                    DELETE FROM mcp_connections
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (authority.principal_id, connection_id),
                )
                conn.execute(
                    """
                    DELETE FROM mcp_connection_slugs
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (authority.principal_id, connection_id),
                )
        finally:
            conn.close()

    def _bump_version(self, authority: ExecutionAuthority, connection_id: str) -> None:
        conn = connect_mcp(self._system_root)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE mcp_connections SET
                        config_version = config_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (authority.principal_id, connection_id),
                )
        finally:
            conn.close()
        self._notify(authority, connection_id)

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
            allowed_tools=request.allowed_tools,
            oauth_client_id=request.oauth_client_id,
            oauth_scopes=request.oauth_scopes,
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
        allowed_tools=update.allowed_tools,
        credential=credential,
        oauth_client_id=update.oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_scopes=update.oauth_scopes,
    )


def _normalize_update(request: MCPConnectionUpdate) -> MCPConnectionUpdate:
    display_name = str(request.display_name or "").strip()
    if not display_name or len(display_name) > 120:
        raise ValueError("MCP display name must contain 1 to 120 characters.")
    url = _sanitize_url(request.url)
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
    return MCPConnectionUpdate(
        display_name=display_name,
        url=url,
        transport=MCPTransport(request.transport),
        auth_mode=auth_mode,
        header_name=header_name,
        enabled=bool(request.enabled),
        allowed_tools=allowed_tools,
        oauth_client_id=oauth_client_id,
        oauth_scopes=oauth_scopes,
    )


def _sanitize_url(value: str) -> str:
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
