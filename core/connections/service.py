"""Authorization-aware built-in connection configuration service."""

from __future__ import annotations

import re
import sqlite3
from uuid import uuid4

from core.identity import ExecutionAuthority, require_current_execution_authority

from .models import (
    GmailPreferences,
    GoogleConnection,
    GoogleConnectionCreate,
    GoogleConnectionUpdate,
)
from .schema import connect_connections, ensure_connections_schema

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class BuiltInConnectionService:
    """Manage non-secret built-in connection metadata by principal."""

    def __init__(self, *, system_root: str) -> None:
        self._system_root = system_root
        ensure_connections_schema(system_root)

    def list_google_connections(self) -> list[GoogleConnection]:
        return self.list_google_connections_for_authority(
            require_current_execution_authority()
        )

    def list_google_connections_for_authority(
        self, authority: ExecutionAuthority
    ) -> list[GoogleConnection]:
        conn = connect_connections(self._system_root)
        try:
            rows = conn.execute(
                """
                SELECT * FROM google_connections
                WHERE owner_principal_id = ?
                ORDER BY is_default DESC, lower(display_name), connection_id
                """,
                (authority.principal_id,),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_google_connection(row) for row in rows]

    def get_google_connection(self) -> GoogleConnection | None:
        """Compatibility accessor returning the current principal's default."""
        return self.get_google_connection_for_authority(
            require_current_execution_authority()
        )

    def get_google_connection_for_authority(
        self,
        authority: ExecutionAuthority,
        connection_id: str | None = None,
    ) -> GoogleConnection | None:
        conn = connect_connections(self._system_root)
        try:
            if connection_id is None:
                row = conn.execute(
                    """
                    SELECT * FROM google_connections
                    WHERE owner_principal_id = ? AND is_default = 1
                    """,
                    (authority.principal_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM google_connections
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (authority.principal_id, _required_id(connection_id)),
                ).fetchone()
        finally:
            conn.close()
        return _row_to_google_connection(row) if row is not None else None

    def get_google_connection_by_slug_for_authority(
        self, authority: ExecutionAuthority, slug: str
    ) -> GoogleConnection | None:
        conn = connect_connections(self._system_root)
        try:
            row = conn.execute(
                """
                SELECT * FROM google_connections
                WHERE owner_principal_id = ? AND slug = ?
                """,
                (authority.principal_id, str(slug or "").strip()),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_google_connection(row) if row is not None else None

    def create_google_connection(
        self, request: GoogleConnectionCreate
    ) -> GoogleConnection:
        return self.create_google_connection_for_authority(
            require_current_execution_authority(), request
        )

    def create_google_connection_for_authority(
        self, authority: ExecutionAuthority, request: GoogleConnectionCreate
    ) -> GoogleConnection:
        connection_id = str(uuid4())
        conn = connect_connections(self._system_root)
        try:
            with conn:
                count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM google_connections WHERE owner_principal_id = ?",
                        (authority.principal_id,),
                    ).fetchone()[0]
                )
                is_default = request.is_default or count == 0
                if is_default:
                    conn.execute(
                        "UPDATE google_connections SET is_default = 0 WHERE owner_principal_id = ?",
                        (authority.principal_id,),
                    )
                slug = _unique_slug(conn, authority.principal_id, request.display_name)
                conn.execute(
                    """
                    INSERT INTO google_connections (
                        owner_principal_id, connection_id, slug, display_name,
                        client_id, is_default, gmail_search_default_results,
                        gmail_search_max_results, gmail_message_max_characters,
                        gmail_thread_max_messages
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        authority.principal_id,
                        connection_id,
                        slug,
                        request.display_name,
                        request.client_id,
                        int(is_default),
                        request.gmail.search_default_results,
                        request.gmail.search_max_results,
                        request.gmail.message_max_characters,
                        request.gmail.thread_max_messages,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Google connection name must be unique.") from exc
        finally:
            conn.close()
        return self._require_for_authority(authority, connection_id)

    def update_google_connection(
        self, connection_id: str, request: GoogleConnectionUpdate
    ) -> GoogleConnection:
        return self.update_google_connection_for_authority(
            require_current_execution_authority(), connection_id, request
        )

    def update_google_connection_for_authority(
        self,
        authority: ExecutionAuthority,
        connection_id: str,
        request: GoogleConnectionUpdate,
    ) -> GoogleConnection:
        existing = self._require_for_authority(authority, connection_id)
        display_name = request.display_name or existing.display_name
        requested_default = (
            existing.is_default if request.is_default is None else request.is_default
        )
        if existing.is_default and not requested_default:
            raise ValueError("Select another default Google connection first.")
        conn = connect_connections(self._system_root)
        try:
            with conn:
                if requested_default and not existing.is_default:
                    conn.execute(
                        "UPDATE google_connections SET is_default = 0 WHERE owner_principal_id = ?",
                        (authority.principal_id,),
                    )
                cursor = conn.execute(
                    """
                    UPDATE google_connections SET display_name = ?, client_id = ?,
                        is_default = ?, gmail_search_default_results = ?,
                        gmail_search_max_results = ?, gmail_message_max_characters = ?,
                        gmail_thread_max_messages = ?, config_version = config_version + 1,
                        oauth_generation = oauth_generation +
                            CASE WHEN client_id <> ? THEN 1 ELSE 0 END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (
                        display_name,
                        request.client_id,
                        int(requested_default),
                        request.gmail.search_default_results,
                        request.gmail.search_max_results,
                        request.gmail.message_max_characters,
                        request.gmail.thread_max_messages,
                        request.client_id,
                        authority.principal_id,
                        existing.connection_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise LookupError("Google connection not found.")
        except sqlite3.IntegrityError as exc:
            raise ValueError("Google connection name must be unique.") from exc
        finally:
            conn.close()
        return self._require_for_authority(authority, existing.connection_id)

    def set_google_connection(
        self, request: GoogleConnectionUpdate
    ) -> GoogleConnection:
        """Compatibility upsert targeting the current principal's default."""
        return self.set_google_connection_for_authority(
            require_current_execution_authority(), request
        )

    def set_google_connection_for_authority(
        self, authority: ExecutionAuthority, request: GoogleConnectionUpdate
    ) -> GoogleConnection:
        existing = self.get_google_connection_for_authority(authority)
        if existing is None:
            return self.create_google_connection_for_authority(
                authority,
                GoogleConnectionCreate(
                    display_name=request.display_name or "Google",
                    client_id=request.client_id,
                    is_default=True,
                    gmail=request.gmail,
                ),
            )
        return self.update_google_connection_for_authority(
            authority, existing.connection_id, request
        )

    def delete_google_connection(
        self,
        connection_id: str | None = None,
        *,
        replacement_default_id: str | None = None,
    ) -> bool:
        return self.delete_google_connection_for_authority(
            require_current_execution_authority(),
            connection_id,
            replacement_default_id=replacement_default_id,
        )

    def delete_google_connection_for_authority(
        self,
        authority: ExecutionAuthority,
        connection_id: str | None = None,
        *,
        replacement_default_id: str | None = None,
    ) -> bool:
        existing = self.validate_google_connection_deletion_for_authority(
            authority,
            connection_id,
            replacement_default_id=replacement_default_id,
        )
        replacement_connection_id = (
            self._require_for_authority(authority, replacement_default_id).connection_id
            if existing.is_default and replacement_default_id is not None
            else None
        )
        conn = connect_connections(self._system_root)
        try:
            with conn:
                if replacement_connection_id is not None:
                    conn.execute(
                        """
                        UPDATE google_connections SET is_default = 0
                        WHERE owner_principal_id = ? AND connection_id = ?
                        """,
                        (authority.principal_id, existing.connection_id),
                    )
                    conn.execute(
                        """
                        UPDATE google_connections SET is_default = 1,
                            config_version = config_version + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE owner_principal_id = ? AND connection_id = ?
                        """,
                        (authority.principal_id, replacement_connection_id),
                    )
                cursor = conn.execute(
                    """
                    DELETE FROM google_connections
                    WHERE owner_principal_id = ? AND connection_id = ?
                    """,
                    (authority.principal_id, existing.connection_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def validate_google_connection_deletion_for_authority(
        self,
        authority: ExecutionAuthority,
        connection_id: str | None = None,
        *,
        replacement_default_id: str | None = None,
    ) -> GoogleConnection:
        """Validate deletion policy without mutating metadata."""
        existing = (
            self.get_google_connection_for_authority(authority, connection_id)
            if connection_id is not None
            else self.get_google_connection_for_authority(authority)
        )
        if existing is None:
            raise LookupError("Google connection not found.")
        others = [
            item
            for item in self.list_google_connections_for_authority(authority)
            if item.connection_id != existing.connection_id
        ]
        if existing.is_default and others:
            if replacement_default_id is None:
                raise ValueError(
                    "Choose a replacement default before deleting this Google connection."
                )
            replacement = self._require_for_authority(authority, replacement_default_id)
            if replacement.connection_id == existing.connection_id:
                raise ValueError("Replacement default must be another connection.")
        return existing

    def _require_for_authority(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> GoogleConnection:
        result = self.get_google_connection_for_authority(authority, connection_id)
        if result is None:
            raise LookupError("Google connection not found.")
        return result


def _required_id(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError("Google connection ID is required.")
    return clean


def _unique_slug(conn: sqlite3.Connection, principal_id: str, display_name: str) -> str:
    base = _SLUG_PATTERN.sub("-", display_name.lower()).strip("-") or "google"
    slug = base
    suffix = 2
    while conn.execute(
        "SELECT 1 FROM google_connections WHERE owner_principal_id = ? AND slug = ?",
        (principal_id, slug),
    ).fetchone():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _row_to_google_connection(row: sqlite3.Row) -> GoogleConnection:
    return GoogleConnection(
        connection_id=str(row["connection_id"]),
        slug=str(row["slug"]),
        display_name=str(row["display_name"]),
        client_id=str(row["client_id"]),
        is_default=bool(row["is_default"]),
        gmail=GmailPreferences(
            search_default_results=int(row["gmail_search_default_results"]),
            search_max_results=int(row["gmail_search_max_results"]),
            message_max_characters=int(row["gmail_message_max_characters"]),
            thread_max_messages=int(row["gmail_thread_max_messages"]),
        ),
        config_version=int(row["config_version"]),
        oauth_generation=int(row["oauth_generation"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
