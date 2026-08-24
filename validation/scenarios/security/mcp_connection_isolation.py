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
    MCPConnectionCreate,
    MCPConnectionService,
    MCPConnectionUpdate,
    MCPTransport,
)
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

        self.assert_no_failures()
        self.teardown_scenario()


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


if __name__ == "__main__":
    asyncio.run(MCPConnectionIsolationScenario().test_scenario())
