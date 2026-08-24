"""Deterministic validation of the headless MCP OAuth coordinator."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-mcp-oauth-flow-")
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from fastmcp.client.auth.oauth import TokenStorageAdapter  # noqa: E402
from mcp.shared.auth import OAuthToken  # noqa: E402

from core.identity import ExecutionAuthority  # noqa: E402
from core.mcp import (  # noqa: E402
    MCPAuthMode,
    MCPConnectionCreate,
    MCPConnectionManager,
    MCPConnectionService,
)
from core.mcp.oauth import MCPOAuthCoordinator, MCPOAuthError, _Attempt  # noqa: E402
from core.secrets import EncryptedSecretsService, SecretKeyring  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class _DeterministicCoordinator(MCPOAuthCoordinator):
    async def _run_attempt(self, attempt: _Attempt) -> None:
        state = "validation-state"
        attempt.authorization_url.set_result(
            f"https://identity.example/authorize?state={state}"
        )
        code, returned_state = await attempt.callback
        if code != "validation-code" or returned_state != state:
            raise ValueError("Unexpected deterministic callback values")
        storage = self._connections.oauth_storage(  # noqa: SLF001
            attempt.authority, attempt.connection.connection_id
        )
        await TokenStorageAdapter(
            async_key_value=storage,
            server_url=attempt.connection.url,
        ).set_tokens(
            OAuthToken(
                access_token="validation-access-token",
                refresh_token="validation-refresh-token",
                expires_in=3600,
            )
        )


class MCPOAuthCoordinatorScenario(BaseScenario):
    async def test_scenario(self) -> None:
        system_root = self.run_path / "system"
        system_root.mkdir()
        secrets = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: bytes(range(32))}, active_version=1),
        )
        service = MCPConnectionService(system_root=str(system_root), secrets=secrets)
        owner = ExecutionAuthority("oauth-flow-owner")
        other = ExecutionAuthority("oauth-flow-other")
        connection = service.create_connection_for_authority(
            owner,
            MCPConnectionCreate(
                display_name="Mail",
                url="https://mail.example/mcp",
                auth_mode=MCPAuthMode.OAUTH,
            ),
        )
        manager = MCPConnectionManager(
            connections=service,
            allow_insecure_http=False,
        )
        coordinator = _DeterministicCoordinator(
            connections=service,
            manager=manager,
        )

        started = await coordinator.start(
            authority=owner,
            connection_id=connection.connection_id,
            redirect_uri="https://assistant.example/api/oauth/callback",
        )
        self.soft_assert_equal(
            (started.state, started.redirect_uri),
            ("validation-state", "https://assistant.example/api/oauth/callback"),
            "OAuth start should return the server authorization state and callback",
        )
        self.soft_assert_equal(
            (
                await coordinator.status(
                    authority=owner, connection_id=connection.connection_id
                )
            ).status,
            "pending",
            "The owner should see the active authorization attempt",
        )
        try:
            await coordinator.status(
                authority=other,
                connection_id=connection.connection_id,
            )
        except LookupError:
            pass
        else:
            self.soft_assert(False, "Another principal must not see OAuth status")

        completed = await coordinator.complete(
            authority=owner,
            connection_id=connection.connection_id,
            code="validation-code",
            state="validation-state",
        )
        self.soft_assert(
            completed.connected,
            "Callback completion should persist a usable OAuth token",
        )
        self.soft_assert_equal(
            (
                await coordinator.status(
                    authority=owner, connection_id=connection.connection_id
                )
            ).status,
            "connected",
            "Durable token state should survive completion of the attempt",
        )
        self.soft_assert(
            b"validation-access-token" not in (system_root / "secrets.db").read_bytes(),
            "Completed OAuth credentials must remain encrypted at rest",
        )

        try:
            await coordinator.complete(
                authority=owner,
                connection_id=connection.connection_id,
                code="validation-code",
                state="wrong-state",
            )
        except MCPOAuthError:
            pass
        else:
            self.soft_assert(False, "A callback without an active attempt must fail")

        await coordinator.disconnect(
            authority=owner,
            connection_id=connection.connection_id,
        )
        self.soft_assert_equal(
            (
                await coordinator.status(
                    authority=owner, connection_id=connection.connection_id
                )
            ).status,
            "disconnected",
            "Disconnect should clear durable OAuth token state",
        )
        await coordinator.shutdown()
        await manager.shutdown()
        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    asyncio.run(MCPOAuthCoordinatorScenario().test_scenario())
