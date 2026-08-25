"""Validate principal-owned Google connection and Gmail scope readiness."""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(
        prefix="assistantmd-google-connection-"
    )
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from core.connections import (  # noqa: E402
    BuiltInConnectionService,
    ConnectionRequirement,
    GoogleConnectionUpdate,
    connection_requirement_available,
)
from core.identity import ExecutionAuthority, use_execution_authority  # noqa: E402
from core.integrations.google import (  # noqa: E402
    GMAIL_READONLY_SCOPE,
    GOOGLE_IDENTITY_SCOPES,
    GoogleCapability,
    GoogleConnectionService,
    GoogleOAuthTokenState,
)
from core.secrets import EncryptedSecretsService, SecretKeyring  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class GmailPrincipalConnectionScenario(BaseScenario):
    """Prove Google secrets, identity, scopes, and availability stay owner-scoped."""

    def test_scenario(self) -> None:
        system_root = self.run_path / "system"
        system_root.mkdir()
        connections = BuiltInConnectionService(system_root=str(system_root))
        secrets = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: bytes(range(32))}, active_version=1),
        )
        google = GoogleConnectionService(connections=connections, secrets=secrets)
        owner = ExecutionAuthority("google-owner")
        other = ExecutionAuthority("google-other")

        self.soft_assert_equal(
            google.status(owner).state,
            "not_configured",
            "Google should begin unconfigured for each principal",
        )
        connections.set_google_connection_for_authority(
            owner,
            GoogleConnectionUpdate(client_id="owner.apps.googleusercontent.com"),
        )
        self.soft_assert_equal(
            google.status(owner).state,
            "not_configured",
            "A visible client ID alone should not make Google usable",
        )
        google.set_client_secret(owner, "owner-client-secret")
        self.soft_assert_equal(
            google.status(owner).state,
            "authorization_required",
            "Client configuration should still require user authorization",
        )

        partial_token = GoogleOAuthTokenState(
            access_token="partial-access-token",
            refresh_token="partial-refresh-token",
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            scopes=GOOGLE_IDENTITY_SCOPES,
            account_id="owner-account-id",
            account_email="owner@example.com",
        )
        google.save_token_state(owner, partial_token)
        partial = google.capability_availability(owner, GoogleCapability.GMAIL_READ)
        self.soft_assert(
            not partial.available and partial.missing_scopes == (GMAIL_READONLY_SCOPE,),
            "A connected Google account without Gmail scope must not expose Gmail",
        )

        ready_token = GoogleOAuthTokenState(
            access_token="owner-access-token",
            refresh_token="owner-refresh-token",
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            scopes=(*GOOGLE_IDENTITY_SCOPES, GMAIL_READONLY_SCOPE),
            account_id="owner-account-id",
            account_email="owner@example.com",
        )
        google.save_token_state(owner, ready_token)
        status = google.status(owner)
        ready = google.capability_availability(owner, GoogleCapability.GMAIL_READ)
        self.soft_assert_equal(
            (
                status.state,
                status.connected,
                status.account_email,
                status.client_secret_present,
                ready.available,
            ),
            ("ready", True, "owner@example.com", True, True),
            "A complete scoped grant should make Gmail available",
        )
        with (
            use_execution_authority(owner),
            patch("core.runtime.state.has_runtime_context", return_value=True),
            patch(
                "core.runtime.state.get_runtime_context",
                return_value=SimpleNamespace(google_connection=google),
            ),
        ):
            self.soft_assert(
                connection_requirement_available(
                    ConnectionRequirement.GOOGLE_GMAIL_READ
                ),
                "Tool binding requirements should resolve the ready Gmail grant",
            )
        self.soft_assert_equal(
            google.status(other).state,
            "not_configured",
            "Another principal must not inherit Google configuration or tokens",
        )

        database_bytes = (system_root / "secrets.db").read_bytes()
        for sensitive in (
            b"owner-client-secret",
            b"owner-access-token",
            b"owner-refresh-token",
            b"owner@example.com",
            b"owner-account-id",
        ):
            self.soft_assert(
                sensitive not in database_bytes,
                "Google secret and account state must remain encrypted at rest",
            )
        self.soft_assert(
            b"owner.apps.googleusercontent.com"
            in (system_root / "connections.db").read_bytes(),
            "The non-secret Google client ID should live in connection metadata",
        )

        google.disconnect(owner)
        self.soft_assert_equal(
            google.status(owner).state,
            "not_configured",
            "Disconnect should remove encrypted client and token state",
        )
        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    GmailPrincipalConnectionScenario().test_scenario()
