"""Security contracts for principal-owned encrypted secret storage."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(
        prefix="assistantmd-secret-boundary-"
    )
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from core.identity import ExecutionAuthority  # noqa: E402
from core.identity.context import use_execution_authority  # noqa: E402
from core.secrets import (  # noqa: E402
    EncryptedSecretsService,
    SecretIntegrityError,
    SecretKeyring,
    initialize_secrets_bootstrap,
    require_secrets_ready,
    reset_secrets_bootstrap_status,
)
from core.secrets.crypto import (  # noqa: E402
    ACTIVE_KEY_VERSION_ENV,
    KEYRING_ENV,
)
from validation.core.base_scenario import BaseScenario  # noqa: E402


class EncryptedSecretsBoundariesScenario(BaseScenario):
    """Prove ownership, integrity, and rotation without exposing values."""

    async def test_scenario(self) -> None:
        locked_root = self.run_path / "locked-system"
        with patch.dict(
            "os.environ",
            {KEYRING_ENV: "", ACTIVE_KEY_VERSION_ENV: ""},
            clear=False,
        ):
            locked_status = initialize_secrets_bootstrap(locked_root)
        self.soft_assert_equal(
            locked_status.state,
            "locked",
            "Missing key configuration should enter secrets-locked mode",
        )
        self.soft_assert(
            not (locked_root / "secrets.db").exists(),
            "Locked bootstrap must not create or mutate the secrets database",
        )
        execution_blocked = False
        try:
            require_secrets_ready()
        except SecretIntegrityError:
            execution_blocked = True
        self.soft_assert(
            execution_blocked,
            "Secrets-locked bootstrap must block model/secret execution",
        )
        reset_secrets_bootstrap_status()

        owner = ExecutionAuthority("secret-owner")
        other = ExecutionAuthority("secret-other")
        key_v1 = bytes(range(32))
        key_v2 = bytes(reversed(range(32)))
        system_root = self.run_path / "system"
        system_root.mkdir()
        service = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: key_v1}, active_version=1),
        )

        missing_authority_failed = False
        try:
            service.get("providers", "API_KEY")
        except RuntimeError:
            missing_authority_failed = True
        self.soft_assert(
            missing_authority_failed,
            "Secret lookup must fail when execution authority is absent",
        )

        with use_execution_authority(owner):
            service.set("providers", "API_KEY", "owner-value")
            service.set("mcp", "gmail-token", "gmail-value")
            self.soft_assert_equal(
                service.get("providers", "API_KEY"),
                "owner-value",
                "The owner should decrypt its own secret",
            )

        with use_execution_authority(other):
            self.soft_assert_equal(
                service.get("providers", "API_KEY"),
                None,
                "A foreign principal should see a missing secret",
            )
            service.set("providers", "API_KEY", "other-value")
            self.soft_assert_equal(
                [(item.namespace, item.name) for item in service.list_metadata()],
                [("providers", "API_KEY")],
                "Metadata enumeration should contain only the active owner",
            )

        with use_execution_authority(owner):
            self.soft_assert_equal(
                service.get("providers", "API_KEY"),
                "owner-value",
                "A same-named foreign secret must not replace the owner's value",
            )
            metadata = service.list_metadata()
            self.soft_assert_equal(
                [(item.namespace, item.name) for item in metadata],
                [("mcp", "gmail-token"), ("providers", "API_KEY")],
                "Metadata should expose names but never values",
            )

        rotating_service = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: key_v1, 2: key_v2}, active_version=2),
        )
        self.soft_assert_equal(
            rotating_service.rotate_all(),
            3,
            "Rotation should update every record using the old version",
        )
        v2_only_service = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={2: key_v2}, active_version=2),
        )
        with use_execution_authority(owner):
            self.soft_assert_equal(
                v2_only_service.get("mcp", "gmail-token"),
                "gmail-value",
                "Rotated values should no longer require the retired key",
            )

        database_path = system_root / "secrets.db"
        conn = sqlite3.connect(database_path)
        try:
            conn.execute(
                """
                UPDATE encrypted_secrets
                SET ciphertext = CAST(ciphertext || X'00' AS BLOB)
                WHERE owner_principal_id = ? AND namespace = ? AND name = ?
                """,
                (owner.principal_id, "mcp", "gmail-token"),
            )
            conn.commit()
        finally:
            conn.close()

        with use_execution_authority(owner):
            tamper_failed = False
            try:
                v2_only_service.get("mcp", "gmail-token")
            except SecretIntegrityError as exc:
                tamper_failed = True
                self.soft_assert(
                    "gmail-value" not in str(exc),
                    "Integrity failures must not expose plaintext",
                )
            self.soft_assert(
                tamper_failed,
                "Modified ciphertext must fail authenticated decryption",
            )

        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    asyncio.run(EncryptedSecretsBoundariesScenario().test_scenario())
