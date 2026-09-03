"""Focused lifecycle tests for retained MCP connection management."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import MethodType, SimpleNamespace
from typing import cast

import pytest
from fastmcp import Client
from mcp.types import Tool

import core.settings as settings
from core.identity import LOCAL_USER_AUTHORITY, ExecutionAuthority
from core.mcp import (
    MCPAuthMode,
    MCPConnection,
    MCPConnectionLease,
    MCPConnectionManager,
    MCPConnectionService,
    MCPTransport,
)


class _ConnectionSource:
    def __init__(self, connections: tuple[MCPConnection, ...]) -> None:
        self.connections = connections

    def list_connections_for_authority(
        self, authority: ExecutionAuthority
    ) -> list[MCPConnection]:
        del authority
        return list(self.connections)

    def get_connection_for_authority(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> MCPConnection | None:
        del authority
        return next(
            (
                connection
                for connection in self.connections
                if connection.connection_id == connection_id
            ),
            None,
        )


def _connection(connection_id: str) -> MCPConnection:
    return MCPConnection(
        connection_id=connection_id,
        slug=connection_id,
        display_name=connection_id,
        url=f"https://{connection_id}.example/mcp",
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_mode=MCPAuthMode.NONE,
        header_name=None,
        enabled=True,
        allow_private_http=False,
        allowed_tools=None,
        credential_present=False,
        config_version=1,
        created_at="2026-09-03T00:00:00Z",
        updated_at="2026-09-03T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_snapshot_cancellation_releases_completed_acquires() -> None:
    first, blocked = _connection("first"), _connection("blocked")
    manager = MCPConnectionManager(
        connections=cast(MCPConnectionService, _ConnectionSource((first, blocked)))
    )
    first_acquired = asyncio.Event()
    never_finish = asyncio.Event()
    release_count = 0

    async def release() -> None:
        nonlocal release_count
        release_count += 1

    async def acquire(
        _manager: MCPConnectionManager,
        authority: ExecutionAuthority,
        connection: MCPConnection,
    ) -> MCPConnectionLease:
        del authority
        if connection.connection_id == blocked.connection_id:
            await never_finish.wait()
        lease = MCPConnectionLease(
            connection=connection,
            client=cast(Client, object()),
            tools=(Tool(name="ready", inputSchema={"type": "object"}),),
            release=release,
        )
        first_acquired.set()
        return lease

    manager.acquire = MethodType(acquire, manager)
    task = asyncio.create_task(manager.acquire_snapshot(LOCAL_USER_AUTHORITY))
    await first_acquired.wait()
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert release_count == 1
    await manager.shutdown()


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(None, 4), ("invalid", 4), (0, 1), (7, 7), (100, 32)],
)
def test_managed_stdio_launch_limit_is_configurable_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
    configured: object,
    expected: int,
) -> None:
    entries = (
        {}
        if configured is None
        else {
            "mcp_max_concurrent_advanced_shell_stdio_launches": SimpleNamespace(
                value=configured
            )
        }
    )
    monkeypatch.setattr(settings, "get_general_settings", lambda: entries)

    assert settings.get_mcp_max_concurrent_advanced_shell_stdio_launches() == expected


@pytest.mark.asyncio
async def test_manager_rejects_non_authoritative_connection_fields() -> None:
    authoritative = _connection("owned")
    manager = MCPConnectionManager(
        connections=cast(MCPConnectionService, _ConnectionSource((authoritative,)))
    )
    forged = replace(authoritative, url="https://substituted.example/mcp")

    with pytest.raises(RuntimeError, match="configuration is not current"):
        await manager.acquire(LOCAL_USER_AUTHORITY, forged)

    await manager.shutdown()
