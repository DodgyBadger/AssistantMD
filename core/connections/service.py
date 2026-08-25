"""Authorization-aware built-in connection configuration service."""

from __future__ import annotations

import sqlite3

from core.identity import ExecutionAuthority, require_current_execution_authority

from .models import GmailPreferences, GoogleConnection, GoogleConnectionUpdate
from .schema import connect_connections, ensure_connections_schema


class BuiltInConnectionService:
    """Manage non-secret built-in connection metadata by principal."""

    def __init__(self, *, system_root: str) -> None:
        self._system_root = system_root
        ensure_connections_schema(system_root)

    def get_google_connection(self) -> GoogleConnection | None:
        """Return current-principal Google configuration when present."""
        return self.get_google_connection_for_authority(
            require_current_execution_authority()
        )

    def get_google_connection_for_authority(
        self, authority: ExecutionAuthority
    ) -> GoogleConnection | None:
        """Return Google configuration owned by an explicit authority."""
        conn = connect_connections(self._system_root)
        try:
            row = conn.execute(
                """
                SELECT client_id, gmail_search_default_results,
                       gmail_search_max_results, gmail_message_max_characters,
                       gmail_thread_max_messages, config_version,
                       created_at, updated_at
                FROM google_connections
                WHERE owner_principal_id = ?
                """,
                (authority.principal_id,),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_google_connection(row) if row is not None else None

    def set_google_connection(
        self, request: GoogleConnectionUpdate
    ) -> GoogleConnection:
        """Create or update current-principal Google configuration."""
        return self.set_google_connection_for_authority(
            require_current_execution_authority(), request
        )

    def set_google_connection_for_authority(
        self,
        authority: ExecutionAuthority,
        request: GoogleConnectionUpdate,
    ) -> GoogleConnection:
        """Create or update Google configuration under explicit authority."""
        conn = connect_connections(self._system_root)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO google_connections (
                        owner_principal_id, client_id,
                        gmail_search_default_results, gmail_search_max_results,
                        gmail_message_max_characters, gmail_thread_max_messages
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(owner_principal_id) DO UPDATE SET
                        client_id = excluded.client_id,
                        gmail_search_default_results =
                            excluded.gmail_search_default_results,
                        gmail_search_max_results = excluded.gmail_search_max_results,
                        gmail_message_max_characters =
                            excluded.gmail_message_max_characters,
                        gmail_thread_max_messages = excluded.gmail_thread_max_messages,
                        config_version = google_connections.config_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        authority.principal_id,
                        request.client_id,
                        request.gmail.search_default_results,
                        request.gmail.search_max_results,
                        request.gmail.message_max_characters,
                        request.gmail.thread_max_messages,
                    ),
                )
        finally:
            conn.close()
        result = self.get_google_connection_for_authority(authority)
        if result is None:
            raise RuntimeError("Google connection update did not persist.")
        return result

    def delete_google_connection(self) -> bool:
        """Delete current-principal non-secret Google configuration."""
        return self.delete_google_connection_for_authority(
            require_current_execution_authority()
        )

    def delete_google_connection_for_authority(
        self, authority: ExecutionAuthority
    ) -> bool:
        """Delete explicit-principal non-secret Google configuration."""
        conn = connect_connections(self._system_root)
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM google_connections WHERE owner_principal_id = ?",
                    (authority.principal_id,),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()


def _row_to_google_connection(row: sqlite3.Row) -> GoogleConnection:
    return GoogleConnection(
        client_id=str(row["client_id"]),
        gmail=GmailPreferences(
            search_default_results=int(row["gmail_search_default_results"]),
            search_max_results=int(row["gmail_search_max_results"]),
            message_max_characters=int(row["gmail_message_max_characters"]),
            thread_max_messages=int(row["gmail_thread_max_messages"]),
        ),
        config_version=int(row["config_version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
