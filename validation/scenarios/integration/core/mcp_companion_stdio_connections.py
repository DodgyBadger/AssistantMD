"""Contracts for credential-free MCP stdio connections in the companion."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-mcp-stdio-")
    direct_root = Path(_direct_run_root.name)
    (direct_root / "data").mkdir()
    (direct_root / "system").mkdir()
    set_bootstrap_roots(direct_root / "data", direct_root / "system")

from mcp.types import Tool  # noqa: E402

from api.models import MCPConnectionImportRequest  # noqa: E402
from api.services.mcp import parse_mcp_connection_import  # noqa: E402
from core.identity import ExecutionAuthority  # noqa: E402
from core.mcp import (  # noqa: E402
    MCPConnectionCreate,
    MCPConnectionManager,
    MCPConnectionService,
    MCPStdioConfig,
    MCPTransport,
)
from core.secrets import EncryptedSecretsService, SecretKeyring  # noqa: E402
from core.tools.advanced_shell import ShellTransportConfig  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class MCPCompanionStdioConnectionsScenario(BaseScenario):
    """Prove stdio persistence, gating, import, and fixed transport behavior."""

    async def test_scenario(self) -> None:
        owner = ExecutionAuthority("stdio-owner")
        system_root = self.run_path / "system"
        system_root.mkdir()
        secrets = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: bytes(range(32))}, active_version=1),
        )
        request = MCPConnectionCreate(
            display_name="Filesystem",
            transport=MCPTransport.COMPANION_STDIO,
            stdio=MCPStdioConfig(
                executable="/home/assistantmd-shell/.local/bin/mcp-server-filesystem",
                arguments=(),
                working_directory="/workspace",
                environment=(("LOG_LEVEL", "warn"),),
                roots=("/workspace",),
            ),
        )
        restricted = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
        )
        try:
            restricted.create_connection_for_authority(owner, request)
        except ValueError as exc:
            self.soft_assert(
                "advanced execution mode" in str(exc),
                "Restricted mode should return a stable stdio gate",
            )
        else:
            self.soft_assert(False, "Restricted mode must reject stdio creation")

        service = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
            companion_stdio_enabled=True,
        )
        connection = service.create_connection_for_authority(owner, request)
        self.soft_assert_equal(
            (connection.url, connection.auth_mode.value, connection.stdio),
            (None, "none", request.stdio),
            "Companion launch metadata should round-trip without an HTTP endpoint",
        )
        self.soft_assert(
            b"LOG_LEVEL" in (system_root / "mcp.db").read_bytes()
            and b"warn" in (system_root / "mcp.db").read_bytes()
            and b"warn" not in (system_root / "secrets.db").read_bytes(),
            "Non-secret environment belongs only in sanitized MCP metadata",
        )

        parsed = parse_mcp_connection_import(
            MCPConnectionImportRequest(
                configuration="""
name: Filesystem
transport: companion_stdio
executable: /home/assistantmd-shell/.local/bin/mcp-server-filesystem
working_directory: /workspace
arguments: []
environment: {}
roots: [/workspace]
allowed_tools: [list_allowed_directories]
enabled: true
"""
            )
        )
        self.soft_assert_equal(
            (
                parsed.display_name,
                parsed.transport,
                parsed.stdio.executable if parsed.stdio else None,
            ),
            (
                "Filesystem",
                "companion_stdio",
                "/home/assistantmd-shell/.local/bin/mcp-server-filesystem",
            ),
            "YAML import should normalize into the ordinary create request",
        )

        key = self.run_path / "client_identity"
        known_hosts = self.run_path / "known_hosts"
        key.write_text("test", encoding="utf-8")
        known_hosts.write_text("test", encoding="utf-8")
        transport_config = ShellTransportConfig(
            host="assistantmd-shell",
            private_key_path=key,
            known_hosts_path=known_hosts,
        )
        clients: list[_StdioClient] = []
        transports: list[_CapturedTransport] = []

        def transport_factory(**kwargs: object) -> _CapturedTransport:
            transport = _CapturedTransport(kwargs)
            transports.append(transport)
            return transport

        def client_factory(_transport: object, **kwargs: object) -> _StdioClient:
            client = _StdioClient(kwargs)
            clients.append(client)
            return client

        manager = MCPConnectionManager(
            connections=service,
            companion_stdio=transport_config,
            idle_timeout_seconds=0,
        )
        with (
            patch("core.mcp.manager.StdioTransport", side_effect=transport_factory),
            patch("core.mcp.manager.Client", side_effect=client_factory),
        ):
            lease = await manager.acquire(owner, connection)
            await lease.close()
            await manager.shutdown()

        self.soft_assert_equal(
            clients[0].roots,
            ["file:///workspace"],
            "Configured companion paths should become MCP file Roots",
        )
        command_args = transports[0].kwargs["args"]
        self.soft_assert(
            isinstance(command_args, list)
            and any(
                str(item).startswith("assistantmd-stdio-v1:") for item in command_args
            )
            and "/home/assistantmd-shell/.local/bin/mcp-server-filesystem"
            not in command_args,
            "The provider launch must cross SSH as a structured envelope",
        )
        self.soft_assert_equal(
            clients[0].exit_count,
            1,
            "Manager shutdown should close the retained stdio client once",
        )

        self.assert_no_failures()
        self.teardown_scenario()


class _CapturedTransport:
    def __init__(self, kwargs: dict[str, object]) -> None:
        self.kwargs = kwargs


class _StdioClient:
    def __init__(self, kwargs: dict[str, object]) -> None:
        self.roots = kwargs.get("roots")
        self.exit_count = 0

    async def __aenter__(self) -> _StdioClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exit_count += 1

    async def list_tools(self, **_kwargs: object) -> list[Tool]:
        return [
            Tool(
                name="list_allowed_directories",
                description="List allowed directories.",
                inputSchema={"type": "object"},
            )
        ]


if __name__ == "__main__":
    import asyncio

    asyncio.run(MCPCompanionStdioConnectionsScenario().test_scenario())
