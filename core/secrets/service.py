"""Synchronous principal-aware encrypted secret operations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from core.identity import ExecutionAuthority, require_current_execution_authority

from .crypto import EncryptedValue, SecretKeyring
from .schema import connect_secrets, ensure_secrets_schema


@dataclass(frozen=True)
class SecretMetadata:
    """Non-sensitive metadata for one stored secret."""

    namespace: str
    name: str
    has_value: bool = True


class EncryptedSecretsService:
    """Store secrets under the current execution principal."""

    def __init__(self, *, system_root: str, keyring: SecretKeyring) -> None:
        self._system_root = system_root
        self._keyring = keyring
        ensure_secrets_schema(system_root)

    def get(self, namespace: str, name: str) -> str | None:
        """Return a current-principal secret without exposing other owners."""
        return self.get_for_authority(
            require_current_execution_authority(), namespace, name
        )

    def set(self, namespace: str, name: str, value: str) -> None:
        """Create or replace a current-principal secret."""
        self.set_for_authority(
            require_current_execution_authority(), namespace, name, value
        )

    def delete(self, namespace: str, name: str) -> bool:
        """Delete a current-principal secret if present."""
        return self.delete_for_authority(
            require_current_execution_authority(), namespace, name
        )

    def list_metadata(self, namespace: str | None = None) -> list[SecretMetadata]:
        """List non-sensitive metadata for the current principal."""
        return self.list_metadata_for_authority(
            require_current_execution_authority(), namespace
        )

    def get_for_authority(
        self, authority: ExecutionAuthority, namespace: str, name: str
    ) -> str | None:
        """Return a secret for an explicitly captured trusted authority."""
        namespace, name = _normalize_identity(namespace, name)
        conn = connect_secrets(self._system_root)
        try:
            row = conn.execute(
                """
                SELECT envelope_version, key_version, nonce, ciphertext
                FROM encrypted_secrets
                WHERE owner_principal_id = ? AND namespace = ? AND name = ?
                """,
                (authority.principal_id, namespace, name),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return self._decrypt_row(
            row,
            owner_principal_id=authority.principal_id,
            namespace=namespace,
            name=name,
        )

    def set_for_authority(
        self,
        authority: ExecutionAuthority,
        namespace: str,
        name: str,
        value: str,
    ) -> None:
        """Write a secret for an explicitly captured trusted authority."""
        namespace, name = _normalize_identity(namespace, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Secret value must be a non-empty string.")
        encrypted = self._keyring.encrypt(
            value,
            owner_principal_id=authority.principal_id,
            namespace=namespace,
            name=name,
        )
        conn = connect_secrets(self._system_root)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO encrypted_secrets (
                        owner_principal_id, namespace, name, envelope_version,
                        key_version, nonce, ciphertext
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(owner_principal_id, namespace, name) DO UPDATE SET
                        envelope_version = excluded.envelope_version,
                        key_version = excluded.key_version,
                        nonce = excluded.nonce,
                        ciphertext = excluded.ciphertext,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        authority.principal_id,
                        namespace,
                        name,
                        encrypted.envelope_version,
                        encrypted.key_version,
                        encrypted.nonce,
                        encrypted.ciphertext,
                    ),
                )
        finally:
            conn.close()

    def delete_for_authority(
        self, authority: ExecutionAuthority, namespace: str, name: str
    ) -> bool:
        """Delete a secret for an explicitly captured trusted authority."""
        namespace, name = _normalize_identity(namespace, name)
        conn = connect_secrets(self._system_root)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    DELETE FROM encrypted_secrets
                    WHERE owner_principal_id = ? AND namespace = ? AND name = ?
                    """,
                    (authority.principal_id, namespace, name),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def list_metadata_for_authority(
        self, authority: ExecutionAuthority, namespace: str | None = None
    ) -> list[SecretMetadata]:
        """List non-sensitive metadata for an explicitly captured authority."""
        conn = connect_secrets(self._system_root)
        try:
            if namespace is None:
                rows = conn.execute(
                    """
                    SELECT namespace, name FROM encrypted_secrets
                    WHERE owner_principal_id = ? ORDER BY namespace, name
                    """,
                    (authority.principal_id,),
                ).fetchall()
            else:
                normalized_namespace, _ = _normalize_identity(namespace, "placeholder")
                rows = conn.execute(
                    """
                    SELECT namespace, name FROM encrypted_secrets
                    WHERE owner_principal_id = ? AND namespace = ? ORDER BY name
                    """,
                    (authority.principal_id, normalized_namespace),
                ).fetchall()
        finally:
            conn.close()
        return [
            SecretMetadata(namespace=row["namespace"], name=row["name"]) for row in rows
        ]

    def rotate_all(self) -> int:
        """Re-encrypt every non-active record atomically with the active key."""
        conn = connect_secrets(self._system_root)
        rotated = 0
        try:
            with conn:
                rows = conn.execute(
                    """
                    SELECT owner_principal_id, namespace, name, envelope_version,
                           key_version, nonce, ciphertext
                    FROM encrypted_secrets WHERE key_version != ?
                    """,
                    (self._keyring.active_version,),
                ).fetchall()
                for row in rows:
                    owner = str(row["owner_principal_id"])
                    namespace = str(row["namespace"])
                    name = str(row["name"])
                    value = self._decrypt_row(
                        row,
                        owner_principal_id=owner,
                        namespace=namespace,
                        name=name,
                    )
                    encrypted = self._keyring.encrypt(
                        value,
                        owner_principal_id=owner,
                        namespace=namespace,
                        name=name,
                    )
                    conn.execute(
                        """
                        UPDATE encrypted_secrets SET envelope_version = ?,
                            key_version = ?, nonce = ?, ciphertext = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE owner_principal_id = ? AND namespace = ? AND name = ?
                        """,
                        (
                            encrypted.envelope_version,
                            encrypted.key_version,
                            encrypted.nonce,
                            encrypted.ciphertext,
                            owner,
                            namespace,
                            name,
                        ),
                    )
                    rotated += 1
                self._verify_all(conn)
        finally:
            conn.close()
        return rotated

    def verify_all(self) -> None:
        """Authenticate every stored record without returning secret values."""
        conn = connect_secrets(self._system_root)
        try:
            self._verify_all(conn)
        finally:
            conn.close()

    def _verify_all(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT owner_principal_id, namespace, name, envelope_version,
                   key_version, nonce, ciphertext FROM encrypted_secrets
            """
        ).fetchall()
        for row in rows:
            self._decrypt_row(
                row,
                owner_principal_id=str(row["owner_principal_id"]),
                namespace=str(row["namespace"]),
                name=str(row["name"]),
            )

    def _decrypt_row(
        self,
        row: sqlite3.Row,
        *,
        owner_principal_id: str,
        namespace: str,
        name: str,
    ) -> str:
        encrypted = EncryptedValue(
            envelope_version=int(row["envelope_version"]),
            key_version=int(row["key_version"]),
            nonce=bytes(row["nonce"]),
            ciphertext=bytes(row["ciphertext"]),
        )
        return self._keyring.decrypt(
            encrypted,
            owner_principal_id=owner_principal_id,
            namespace=namespace,
            name=name,
        )


def _normalize_identity(namespace: str, name: str) -> tuple[str, str]:
    normalized_namespace = str(namespace or "").strip()
    normalized_name = str(name or "").strip()
    if not normalized_namespace:
        raise ValueError("Secret namespace is required.")
    if not normalized_name:
        raise ValueError("Secret name is required.")
    if len(normalized_namespace) > 128 or len(normalized_name) > 256:
        raise ValueError("Secret namespace or name exceeds its storage limit.")
    return normalized_namespace, normalized_name
