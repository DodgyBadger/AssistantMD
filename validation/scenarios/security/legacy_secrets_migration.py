"""Durable contracts for the one-time plaintext secrets migration."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(
        prefix="assistantmd-secret-migration-"
    )
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from core.identity import LOCAL_USER_AUTHORITY, SYSTEM_AUTHORITY  # noqa: E402
from core.secrets import EncryptedSecretsService, SecretKeyring  # noqa: E402
from core.secrets.legacy_migration import (  # noqa: E402
    DEFAULT_NAMESPACE,
    LEGACY_BACKUP_FILENAME,
    migrate_legacy_secrets_yaml,
)
from validation.core.base_scenario import BaseScenario  # noqa: E402


class LegacySecretsMigrationScenario(BaseScenario):
    """Prove verified import, ownership, retirement, and failure rollback."""

    async def test_scenario(self) -> None:
        keyring = SecretKeyring(keys={1: bytes(range(32))}, active_version=1)
        successful_root = self.run_path / "successful-system"
        successful_root.mkdir()
        source_path = successful_root / "secrets.yaml"
        source_path.write_text(
            """OPENAI_API_KEY: user-api-key
LOGFIRE_TOKEN: system-logfire-token
OPENAI_OAUTH_TOKEN_STATE: reconnect-required
OPENAI_OAUTH_PENDING_STATE: discard-pending
EMPTY_VALUE:
""",
            encoding="utf-8",
        )
        service = EncryptedSecretsService(
            system_root=str(successful_root), keyring=keyring
        )

        result = migrate_legacy_secrets_yaml(
            system_root=successful_root, service=service
        )
        self.soft_assert_equal(result.phase, "complete", "Migration should complete")
        self.soft_assert_equal(
            result.imported_count,
            2,
            "Only non-empty static and operational values should import",
        )
        self.soft_assert_equal(
            result.skipped_oauth_count,
            2,
            "OAuth token and pending state should require reconnection",
        )
        self.soft_assert(
            not source_path.exists(),
            "Verified migration should retire the live plaintext file",
        )
        backup_path = successful_root / LEGACY_BACKUP_FILENAME
        self.soft_assert(
            backup_path.exists(),
            "Verified migration should preserve the legacy file as a backup",
        )
        self.soft_assert(
            "OPENAI_API_KEY: user-api-key" in backup_path.read_text(encoding="utf-8"),
            "The retired backup should retain the original rollback data",
        )
        self.soft_assert_equal(
            service.get_for_authority(
                LOCAL_USER_AUTHORITY, DEFAULT_NAMESPACE, "OPENAI_API_KEY"
            ),
            "user-api-key",
            "User API keys should belong to local-user",
        )
        self.soft_assert_equal(
            service.get_for_authority(
                SYSTEM_AUTHORITY, DEFAULT_NAMESPACE, "LOGFIRE_TOKEN"
            ),
            "system-logfire-token",
            "Operational Logfire state should belong to system",
        )
        self.soft_assert_equal(
            service.get_for_authority(
                LOCAL_USER_AUTHORITY,
                DEFAULT_NAMESPACE,
                "OPENAI_OAUTH_TOKEN_STATE",
            ),
            None,
            "OAuth token state must not migrate",
        )

        repeated = migrate_legacy_secrets_yaml(
            system_root=successful_root, service=service
        )
        self.soft_assert_equal(
            repeated.imported_count,
            2,
            "Completed migration should be idempotent",
        )

        invalid_root = self.run_path / "invalid-system"
        invalid_root.mkdir()
        invalid_source = invalid_root / "secrets.yaml"
        invalid_source.write_text("OPENAI_API_KEY: 123\n", encoding="utf-8")
        invalid_service = EncryptedSecretsService(
            system_root=str(invalid_root), keyring=keyring
        )
        invalid_failed = False
        try:
            migrate_legacy_secrets_yaml(
                system_root=invalid_root, service=invalid_service
            )
        except ValueError:
            invalid_failed = True
        self.soft_assert(
            invalid_failed,
            "Malformed legacy values should fail before importing anything",
        )
        self.soft_assert(
            invalid_source.exists(),
            "Failed migration must preserve the plaintext source",
        )
        conn = sqlite3.connect(invalid_root / "secrets.db")
        try:
            secret_count = int(
                conn.execute("SELECT COUNT(*) FROM encrypted_secrets").fetchone()[0]
            )
            migration_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM secrets_bootstrap_migrations"
                ).fetchone()[0]
            )
        finally:
            conn.close()
        self.soft_assert_equal(
            secret_count, 0, "Failed migration must not leave partial secret rows"
        )
        self.soft_assert_equal(
            migration_count, 0, "Failed migration must not record completion"
        )

        collision_root = self.run_path / "backup-collision-system"
        collision_root.mkdir()
        collision_source = collision_root / "secrets.yaml"
        collision_source.write_text("OPENAI_API_KEY: new-value\n", encoding="utf-8")
        collision_backup = collision_root / LEGACY_BACKUP_FILENAME
        collision_backup.write_text("OPENAI_API_KEY: old-value\n", encoding="utf-8")
        collision_service = EncryptedSecretsService(
            system_root=str(collision_root), keyring=keyring
        )
        collision_failed = False
        try:
            migrate_legacy_secrets_yaml(
                system_root=collision_root, service=collision_service
            )
        except FileExistsError:
            collision_failed = True
        self.soft_assert(
            collision_failed,
            "Migration should not overwrite an existing legacy backup",
        )
        self.soft_assert_equal(
            collision_backup.read_text(encoding="utf-8"),
            "OPENAI_API_KEY: old-value\n",
            "A backup collision should preserve the existing rollback file",
        )

        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    asyncio.run(LegacySecretsMigrationScenario().test_scenario())
