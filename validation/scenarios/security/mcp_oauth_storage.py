"""Security contracts for encrypted principal-owned MCP OAuth storage."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-mcp-oauth-")
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from fastmcp.client.auth.oauth import TokenStorageAdapter  # noqa: E402
from mcp.shared.auth import OAuthToken  # noqa: E402

from core.identity import ExecutionAuthority  # noqa: E402
from core.mcp import ConnectedMCPOAuth, EncryptedMCPOAuthStorage  # noqa: E402
from core.mcp.oauth_storage import has_mcp_oauth_tokens  # noqa: E402
from core.secrets import EncryptedSecretsService, SecretKeyring  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class MCPOAuthStorageScenario(BaseScenario):
    """Prove FastMCP OAuth state is encrypted and isolated by principal."""

    async def test_scenario(self) -> None:
        system_root = self.run_path / "system"
        system_root.mkdir()
        secrets = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: bytes(range(32))}, active_version=1),
        )
        owner = ExecutionAuthority("oauth-owner")
        other = ExecutionAuthority("oauth-other")
        owner_store = EncryptedMCPOAuthStorage(
            secrets=secrets,
            authority=owner,
            connection_id="shared-connection-id",
        )
        other_store = EncryptedMCPOAuthStorage(
            secrets=secrets,
            authority=other,
            connection_id="shared-connection-id",
        )
        owner_adapter = TokenStorageAdapter(
            async_key_value=owner_store,
            server_url="https://mail.example/mcp",
        )
        other_adapter = TokenStorageAdapter(
            async_key_value=other_store,
            server_url="https://mail.example/mcp",
        )

        await owner_adapter.set_tokens(
            OAuthToken(
                access_token="owner-access-token",
                refresh_token="owner-refresh-token",
                expires_in=3600,
            )
        )
        await other_adapter.set_tokens(
            OAuthToken(access_token="other-access-token", expires_in=1800)
        )

        owner_tokens = await owner_adapter.get_tokens()
        other_tokens = await other_adapter.get_tokens()
        self.soft_assert_equal(
            owner_tokens.access_token if owner_tokens else None,
            "owner-access-token",
            "FastMCP should round-trip the owner's encrypted OAuth token",
        )
        self.soft_assert_equal(
            other_tokens.access_token if other_tokens else None,
            "other-access-token",
            "The same MCP connection identity must remain principal-isolated",
        )
        self.soft_assert(
            (await owner_adapter.get_token_expiry()) is not None,
            "FastMCP token expiry metadata should persist with the token",
        )
        self.soft_assert(
            await has_mcp_oauth_tokens(
                storage=owner_store,
                mcp_url="https://mail.example/mcp",
            ),
            "Runtime connection preflight should recognize persisted OAuth tokens",
        )
        database_bytes = (system_root / "secrets.db").read_bytes()
        self.soft_assert(
            b"owner-access-token" not in database_bytes
            and b"owner-refresh-token" not in database_bytes
            and b"other-access-token" not in database_bytes,
            "OAuth token material must not appear in plaintext storage",
        )

        await owner_adapter.clear()
        self.soft_assert_equal(
            await owner_adapter.get_tokens(),
            None,
            "Clearing one principal's OAuth state should remove its tokens",
        )
        self.soft_assert(
            not await has_mcp_oauth_tokens(
                storage=owner_store,
                mcp_url="https://mail.example/mcp",
            ),
            "Disconnected OAuth state should fail runtime preflight without a browser",
        )
        self.soft_assert_equal(
            (await other_adapter.get_tokens()).access_token,
            "other-access-token",
            "Clearing one principal must not affect another principal",
        )

        await owner_store.put("expired", {"secret": "discard-me"}, ttl=-1)
        self.soft_assert_equal(
            await owner_store.get("expired"),
            None,
            "Expired OAuth state should be deleted on read",
        )
        connected_auth = ConnectedMCPOAuth(
            mcp_url="https://mail.example/mcp",
            token_storage=other_store,
        )
        try:
            await connected_auth.redirect_handler("https://identity.example/authorize")
        except ValueError as exc:
            self.soft_assert(
                "Connect this server in System" in str(exc),
                "Runtime OAuth must report an actionable reconnect requirement",
            )
        else:
            self.soft_assert(False, "Runtime OAuth must never launch a browser flow")

        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    asyncio.run(MCPOAuthStorageScenario().test_scenario())
