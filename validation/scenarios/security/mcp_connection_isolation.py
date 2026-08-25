"""Security contracts for principal-owned MCP connection management."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-mcp-domain-")
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from core.identity import ExecutionAuthority, use_execution_authority  # noqa: E402
from core.mcp import (  # noqa: E402
    MCPAuthMode,
    MCPConnection,
    MCPConnectionCreate,
    MCPConnectionManager,
    MCPConnectionService,
    MCPConnectionUpdate,
    MCPTransport,
)
from core.mcp.network import MCPNetworkPolicyError, validate_mcp_endpoint  # noqa: E402
from core.mcp.testing import test_mcp_connection_runtime  # noqa: E402
from core.secrets import EncryptedSecretsService, SecretKeyring  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class MCPConnectionIsolationScenario(BaseScenario):
    """Prove connection identity, credentials, and enumeration are owner-scoped."""

    async def test_scenario(self) -> None:
        owner = ExecutionAuthority("mcp-owner")
        other = ExecutionAuthority("mcp-other")
        system_root = self.run_path / "system"
        system_root.mkdir()
        secrets = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: bytes(range(32))}, active_version=1),
        )
        service = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
        )

        owner_connection = service.create_connection_for_authority(
            owner,
            MCPConnectionCreate(
                display_name="Gmail",
                url="https://gmail.example/mcp",
                auth_mode=MCPAuthMode.BEARER,
                credential="owner-token",
            ),
        )
        other_connection = service.create_connection_for_authority(
            other,
            MCPConnectionCreate(
                display_name="Gmail",
                url="https://other.example/mcp",
                auth_mode=MCPAuthMode.BEARER,
                credential="other-token",
            ),
        )
        oauth_connection = service.create_connection_for_authority(
            owner,
            MCPConnectionCreate(
                display_name="Workspace",
                url="https://workspace.example/mcp",
                auth_mode=MCPAuthMode.OAUTH,
                oauth_client_id="owner-client-id",
                oauth_client_secret="owner-client-secret",
                oauth_scopes=("mail.read", "mail.compose"),
            ),
        )

        self.soft_assert_equal(
            owner_connection.slug,
            other_connection.slug,
            "Immutable model-facing slugs may repeat safely across principals",
        )
        self.soft_assert_equal(
            service.get_connection_for_authority(other, owner_connection.connection_id),
            None,
            "A foreign connection ID must look absent",
        )
        self.soft_assert_equal(
            service.resolve_credential(owner, owner_connection.connection_id),
            "owner-token",
            "Credential lookup should resolve the matching owner's value",
        )
        self.soft_assert_equal(
            service.resolve_credential(other, other_connection.connection_id),
            "other-token",
            "Same-named credentials must remain independently owned",
        )
        self.soft_assert_equal(
            (
                oauth_connection.oauth_client_id,
                oauth_connection.oauth_client_secret_present,
                oauth_connection.oauth_scopes,
            ),
            ("owner-client-id", True, ("mail.read", "mail.compose")),
            "OAuth client metadata should round-trip without exposing its secret",
        )
        self.soft_assert_equal(
            service.resolve_oauth_client_secret(owner, oauth_connection.connection_id),
            "owner-client-secret",
            "OAuth client secrets should resolve only under matching authority",
        )
        try:
            service.resolve_oauth_client_secret(other, oauth_connection.connection_id)
        except LookupError:
            pass
        else:
            self.soft_assert(
                False, "A foreign principal must not resolve OAuth secrets"
            )
        self.soft_assert(
            b"owner-client-secret" not in (system_root / "secrets.db").read_bytes(),
            "OAuth client secrets must be encrypted at rest",
        )

        with use_execution_authority(owner):
            updated = service.update_connection(
                owner_connection.connection_id,
                MCPConnectionUpdate(
                    display_name="Personal Gmail",
                    url=owner_connection.url,
                    transport=MCPTransport.STREAMABLE_HTTP,
                    auth_mode=MCPAuthMode.BEARER,
                    header_name=None,
                    enabled=False,
                    allowed_tools=("search_messages",),
                ),
            )
        self.soft_assert_equal(
            updated.slug,
            owner_connection.slug,
            "Display-name updates must not change the persisted tool prefix",
        )
        self.soft_assert_equal(
            updated.config_version,
            owner_connection.config_version + 1,
            "Mutable configuration should advance its invalidation version",
        )
        self.soft_assert(
            updated.credential_present
            and "owner-token" not in repr(updated)
            and "other-token" not in repr(updated),
            "Sanitized records should expose credential presence but never values",
        )
        self.soft_assert(
            b"owner-token" not in (system_root / "mcp.db").read_bytes()
            and b"owner-token" not in (system_root / "secrets.db").read_bytes(),
            "Neither MCP metadata nor encrypted storage may contain credential plaintext",
        )

        with patch("core.mcp.testing.Client", return_value=_SuccessfulTestClient()):
            ready_result = await test_mcp_connection_runtime(
                updated,
                "owner-token",
            )
        self.soft_assert_equal(
            (
                ready_result.status,
                ready_result.ready,
                ready_result.tool_count,
                ready_result.tool_names,
            ),
            ("ready", True, 1, ("search_messages",)),
            "Connection testing should report effective allowlisted tools",
        )

        with patch("core.mcp.testing.Client", return_value=_RejectedTestClient()):
            rejected_result = await test_mcp_connection_runtime(
                updated,
                "owner-token",
            )
        self.soft_assert_equal(
            rejected_result.status,
            "authentication_failed",
            "HTTP authentication rejection should have a stable sanitized status",
        )
        self.soft_assert(
            "owner-token" not in rejected_result.message
            and updated.url not in rejected_result.message,
            "Connection-test failures must not expose credentials or raw URLs",
        )

        with use_execution_authority(owner):
            service.delete_connection(owner_connection.connection_id)
            replacement = service.create_connection(
                MCPConnectionCreate(
                    display_name="Gmail",
                    url="https://replacement.example/mcp",
                )
            )
        self.soft_assert_equal(
            replacement.slug,
            "gmail-2",
            "A retired slug must never be reassigned to another connection",
        )

        await self._assert_managed_connection_lifecycle(
            service=service,
            owner=owner,
            other=other,
            owner_connection=replacement,
            other_connection=other_connection,
        )
        await self._assert_network_policy()

        self.assert_no_failures()
        self.teardown_scenario()

    async def _assert_managed_connection_lifecycle(
        self,
        *,
        service: MCPConnectionService,
        owner: ExecutionAuthority,
        other: ExecutionAuthority,
        owner_connection: MCPConnection,
        other_connection: MCPConnection,
    ) -> None:
        clients: list[_ManagedTestClient] = []

        def client_factory(*_args: object, **_kwargs: object) -> _ManagedTestClient:
            client = _ManagedTestClient()
            clients.append(client)
            return client

        manager = MCPConnectionManager(
            connections=service,
            allow_insecure_http=True,
            idle_timeout_seconds=0,
        )
        with (
            patch("core.mcp.manager.Client", side_effect=client_factory),
            patch("core.mcp.manager.validate_mcp_endpoint", new=_allow_endpoint),
        ):
            owner_leases = await asyncio.gather(
                manager.acquire(owner, owner_connection),
                manager.acquire(owner, owner_connection),
            )
            self.soft_assert_equal(
                len(clients),
                1,
                "Concurrent cold callers should share one initialization",
            )
            other_lease = await manager.acquire(other, other_connection)
            self.soft_assert_equal(
                len(clients),
                2,
                "The same manager must retain separate clients per principal",
            )

            await owner_leases[0].close()
            self.soft_assert_equal(
                await manager.evict_idle(),
                0,
                "An active lease must prevent idle eviction",
            )
            await owner_leases[1].close()
            self.soft_assert_equal(
                await manager.evict_idle(),
                1,
                "An idle unleased client should be evicted",
            )
            replacement_lease = await manager.acquire(owner, owner_connection)
            self.soft_assert_equal(
                len(clients),
                3,
                "An evicted connection should initialize again on demand",
            )
            manager.invalidate(owner.principal_id, owner_connection.connection_id)
            await asyncio.sleep(0)
            await replacement_lease.close()
            await asyncio.sleep(0)
            invalidated_lease = await manager.acquire(owner, owner_connection)
            self.soft_assert_equal(
                len(clients),
                4,
                "Invalidation should force the next lease onto a fresh client",
            )
            await invalidated_lease.close()
            await other_lease.close()
            await manager.shutdown()

        self.soft_assert(
            all(client.exit_count == 1 for client in clients),
            "Eviction, invalidation, and shutdown should close every client once "
            f"(close counts: {[client.exit_count for client in clients]})",
        )

    async def _assert_network_policy(self) -> None:
        with patch(
            "core.mcp.network._resolve_addresses",
            return_value=("172.18.0.9",),
        ):
            try:
                await validate_mcp_endpoint(
                    "http://marimo:8080/mcp/server",
                    allow_insecure_http=False,
                )
                rejected_local_http = False
            except MCPNetworkPolicyError:
                rejected_local_http = True
            self.soft_assert(
                rejected_local_http,
                "Local HTTP MCP should require the explicit development allowance",
            )
            allowed = await validate_mcp_endpoint(
                "http://marimo:8080/mcp/server",
                allow_insecure_http=True,
            )
            self.soft_assert_equal(
                allowed.addresses,
                ("172.18.0.9",),
                "Explicit development allowance should admit local HTTP MCP",
            )
        with patch(
            "core.mcp.network._resolve_addresses",
            return_value=("8.8.8.8",),
        ):
            try:
                await validate_mcp_endpoint(
                    "http://public.example/mcp",
                    allow_insecure_http=True,
                )
                rejected_public_http = False
            except MCPNetworkPolicyError:
                rejected_public_http = True
            self.soft_assert(
                rejected_public_http,
                "The development allowance must not permit public HTTP MCP",
            )
            secure = await validate_mcp_endpoint(
                "https://public.example/mcp",
                allow_insecure_http=False,
            )
            self.soft_assert(
                secure.secure,
                "Public MCP connections should require and accept HTTPS",
            )


@dataclass(frozen=True)
class _TestTool:
    name: str


class _SuccessfulTestClient:
    async def __aenter__(self) -> _SuccessfulTestClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def list_tools(self, *, max_pages: int) -> list[_TestTool]:
        assert max_pages > 0
        return [_TestTool("search_messages"), _TestTool("archive_message")]


class _RejectedTestClient:
    async def __aenter__(self) -> _RejectedTestClient:
        request = httpx.Request("POST", "https://private.example/mcp")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError(
            "credential-bearing raw transport failure",
            request=request,
            response=response,
        )

    async def __aexit__(self, *_args: object) -> None:
        return None


class _ManagedTestClient:
    def __init__(self) -> None:
        self.exit_count = 0

    async def __aenter__(self) -> _ManagedTestClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exit_count += 1

    async def list_tools(self, *, max_pages: int) -> list[_TestTool]:
        assert max_pages > 0
        return [_TestTool("search_messages")]


async def _allow_endpoint(*_args: object, **_kwargs: object) -> None:
    return None


if __name__ == "__main__":
    asyncio.run(MCPConnectionIsolationScenario().test_scenario())
