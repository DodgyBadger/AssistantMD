"""Principal-scoped retained MCP connections and settled tool catalogs."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from fastmcp import Client
from fastmcp.client.client import MessageHandler
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from mcp.types import Tool, ToolListChangedNotification

from core.identity import ExecutionAuthority
from core.logger import UnifiedLogger
from core.web.security import sanitize_url_for_log

from .models import (
    MCPAuthMode,
    MCPConnection,
    MCPConnectionTestResult,
    MCPTransport,
)
from .network import MCPNetworkPolicyError, validate_mcp_endpoint
from .oauth_storage import (
    ConnectedMCPOAuth,
    EncryptedMCPOAuthStorage,
    has_mcp_oauth_tokens,
)
from .service import MCPConnectionService

MCP_CONNECT_TIMEOUT_SECONDS = 10.0
MCP_INIT_TIMEOUT_SECONDS = 8.0
MCP_READ_TIMEOUT_SECONDS = 30.0
MCP_CLOSE_TIMEOUT_SECONDS = 5.0
MCP_IDLE_TIMEOUT_SECONDS = 15 * 60.0
MCP_MAX_TOOL_PAGES = 10
MCP_CONNECT_ATTEMPTS = 2

logger = UnifiedLogger(tag="mcp-manager")

_ConnectionKey = tuple[str, str, int]


@dataclass(frozen=True)
class MCPUnavailableConnection:
    """Sanitized connection failure safe for user/model-facing summaries."""

    connection_id: str
    display_name: str
    status: str
    message: str


@dataclass(frozen=True)
class MCPReadinessSnapshot:
    """Settled ready and unavailable connections for one execution boundary."""

    leases: tuple[MCPConnectionLease, ...]
    unavailable: tuple[MCPUnavailableConnection, ...]

    async def close(self) -> None:
        """Release all ready connection leases."""
        await asyncio.gather(*(lease.close() for lease in self.leases))

    async def __aenter__(self) -> MCPReadinessSnapshot:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()


class MCPConnectionLease:
    """One active-use claim on a frozen managed client/catalog pair."""

    def __init__(
        self,
        *,
        connection: MCPConnection,
        client: Client,
        tools: tuple[Tool, ...],
        release: Callable[[], Awaitable[None]],
    ) -> None:
        self.connection = connection
        self.client = client
        self.tools = tools
        self._release = release
        self._closed = False

    async def close(self) -> None:
        """Release this lease exactly once."""
        if self._closed:
            return
        self._closed = True
        await self._release()

    async def __aenter__(self) -> MCPConnectionLease:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()


@dataclass
class _ManagedConnection:
    connection: MCPConnection
    client: Client
    tools: tuple[Tool, ...]
    active_leases: int
    last_used: float
    invalidated: bool = False


class MCPConnectionManager:
    """Own retained FastMCP clients without crossing principal boundaries."""

    def __init__(
        self,
        *,
        connections: MCPConnectionService,
        allow_insecure_http: bool,
        idle_timeout_seconds: float = MCP_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        self._connections = connections
        self._allow_insecure_http = allow_insecure_http
        self._idle_timeout_seconds = idle_timeout_seconds
        self._entries: dict[_ConnectionKey, _ManagedConnection] = {}
        self._locks: dict[_ConnectionKey, asyncio.Lock] = {}
        self._state_lock = asyncio.Lock()
        self._closed = False
        self._loop = asyncio.get_running_loop()
        self._idle_task: asyncio.Task[None] | None = None
        self._invalidation_tasks: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        """Start bounded idle-client eviction without connecting any server."""
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_eviction_loop())

    async def acquire_snapshot(
        self,
        authority: ExecutionAuthority,
    ) -> MCPReadinessSnapshot:
        """Settle every enabled connection as ready or sanitized unavailable."""
        connections = [
            connection
            for connection in self._connections.list_connections_for_authority(
                authority
            )
            if connection.enabled
        ]
        results = await asyncio.gather(
            *(self.acquire(authority, connection) for connection in connections),
            return_exceptions=True,
        )
        leases: list[MCPConnectionLease] = []
        unavailable: list[MCPUnavailableConnection] = []
        for connection, result in zip(connections, results, strict=True):
            if isinstance(result, MCPConnectionLease):
                leases.append(result)
                continue
            unavailable.append(_unavailable(connection, result))
        return MCPReadinessSnapshot(tuple(leases), tuple(unavailable))

    async def test_connection(
        self,
        authority: ExecutionAuthority,
        connection: MCPConnection,
    ) -> MCPConnectionTestResult:
        """Warm one managed connection and return its sanitized effective catalog."""
        try:
            lease = await self._acquire(
                authority,
                connection,
                require_enabled=False,
            )
        except BaseException as exc:
            unavailable = _unavailable(connection, exc)
            return MCPConnectionTestResult(
                status=unavailable.status,
                ready=False,
                tool_count=None,
                tool_names=(),
                message=unavailable.message,
            )
        try:
            names = tuple(tool.name for tool in lease.tools)
            if connection.allowed_tools is not None:
                allowed = set(connection.allowed_tools)
                names = tuple(name for name in names if name in allowed)
            return MCPConnectionTestResult(
                status="ready",
                ready=True,
                tool_count=len(names),
                tool_names=names,
                message=(
                    "Connected successfully and discovered "
                    f"{len(names)} available MCP tool(s)."
                ),
            )
        finally:
            await lease.close()

    async def acquire(
        self,
        authority: ExecutionAuthority,
        connection: MCPConnection,
    ) -> MCPConnectionLease:
        """Acquire one versioned connection, sharing concurrent cold starts."""
        return await self._acquire(authority, connection, require_enabled=True)

    async def _acquire(
        self,
        authority: ExecutionAuthority,
        connection: MCPConnection,
        *,
        require_enabled: bool,
    ) -> MCPConnectionLease:
        if self._closed:
            raise RuntimeError("MCP connection manager is closed.")
        if require_enabled and not connection.enabled:
            raise RuntimeError("MCP connection is disabled.")
        key = _key(authority, connection)
        async with self._state_lock:
            lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            async with self._state_lock:
                entry = self._entries.get(key)
                if entry is not None and not entry.invalidated:
                    entry.active_leases += 1
                    entry.last_used = time.monotonic()
                    return self._lease(key, entry)

            entry = await self._connect_with_retry(authority, connection)
            async with self._state_lock:
                if self._closed:
                    await _close_client(entry.client)
                    raise RuntimeError("MCP connection manager is closed.")
                existing = self._entries.get(key)
                if existing is not None and not existing.invalidated:
                    await _close_client(entry.client)
                    existing.active_leases += 1
                    existing.last_used = time.monotonic()
                    return self._lease(key, existing)
                entry.active_leases = 1
                self._entries[key] = entry
                return self._lease(key, entry)

    def invalidate(self, principal_id: str, connection_id: str) -> None:
        """Mark matching clients stale; active leases finish against their snapshot."""
        self._loop.call_soon_threadsafe(
            self._spawn_invalidation,
            principal_id,
            connection_id,
        )

    async def evict_idle(self) -> int:
        """Close retained clients that have no active lease and exceeded idle TTL."""
        cutoff = time.monotonic() - self._idle_timeout_seconds
        async with self._state_lock:
            keys = [
                key
                for key, entry in self._entries.items()
                if entry.active_leases == 0 and entry.last_used <= cutoff
            ]
            entries = [self._entries.pop(key) for key in keys]
        await asyncio.gather(*(_close_client(entry.client) for entry in entries))
        return len(entries)

    async def shutdown(self) -> None:
        """Stop accepting leases and close every retained client."""
        async with self._state_lock:
            if self._closed:
                return
            self._closed = True
        idle_task = self._idle_task
        self._idle_task = None
        if idle_task is not None:
            idle_task.cancel()
            await asyncio.gather(idle_task, return_exceptions=True)
        invalidation_tasks = tuple(self._invalidation_tasks)
        if invalidation_tasks:
            await asyncio.gather(*invalidation_tasks, return_exceptions=True)
        async with self._state_lock:
            entries = list(self._entries.values())
            self._entries.clear()
            self._locks.clear()
        await asyncio.gather(*(_close_client(entry.client) for entry in entries))

    def _spawn_invalidation(self, principal_id: str, connection_id: str) -> None:
        if self._closed:
            return
        task = asyncio.create_task(self._invalidate(principal_id, connection_id))
        self._invalidation_tasks.add(task)
        task.add_done_callback(self._invalidation_tasks.discard)

    async def _idle_eviction_loop(self) -> None:
        interval = max(1.0, min(60.0, self._idle_timeout_seconds))
        while True:
            await asyncio.sleep(interval)
            await self.evict_idle()

    async def _connect(
        self,
        authority: ExecutionAuthority,
        connection: MCPConnection,
    ) -> _ManagedConnection:
        await validate_mcp_endpoint(
            connection.url,
            allow_insecure_http=self._allow_insecure_http,
        )
        credential = self._connections.resolve_credential(
            authority,
            connection.connection_id,
        )
        oauth_storage = (
            self._connections.oauth_storage(authority, connection.connection_id)
            if connection.auth_mode is MCPAuthMode.OAUTH
            else None
        )
        if oauth_storage is not None and not await has_mcp_oauth_tokens(
            storage=oauth_storage,
            mcp_url=connection.url,
        ):
            raise ValueError(
                "MCP OAuth authorization is required. Connect this server in System."
            )
        headers, auth = _build_auth(
            connection,
            credential,
            oauth_storage=oauth_storage,
            allow_insecure_http=self._allow_insecure_http,
        )
        transport = (
            StreamableHttpTransport(
                connection.url,
                headers=headers,
                auth=auth,
                httpx_client_factory=_mcp_http_client,
            )
            if connection.transport is MCPTransport.STREAMABLE_HTTP
            else SSETransport(
                connection.url,
                headers=headers,
                auth=auth,
                httpx_client_factory=_mcp_http_client,
            )
        )
        client = Client(
            transport,
            message_handler=_CatalogChangeHandler(
                lambda: self.invalidate(
                    authority.principal_id,
                    connection.connection_id,
                )
            ),
            init_timeout=MCP_INIT_TIMEOUT_SECONDS,
            timeout=MCP_READ_TIMEOUT_SECONDS,
        )
        try:
            async with asyncio.timeout(MCP_CONNECT_TIMEOUT_SECONDS):
                await client.__aenter__()
                tools = await client.list_tools(max_pages=MCP_MAX_TOOL_PAGES)
        except BaseException:
            await _close_client(client)
            raise
        logger.info(
            "MCP connection ready",
            data={
                "event": "mcp_connection_ready",
                "principal_id": authority.principal_id,
                "connection_id": connection.connection_id,
                "url": sanitize_url_for_log(connection.url),
                "transport": connection.transport.value,
                "tool_count": len(tools),
            },
        )
        return _ManagedConnection(
            connection=connection,
            client=client,
            tools=tuple(tools),
            active_leases=0,
            last_used=time.monotonic(),
        )

    async def _connect_with_retry(
        self,
        authority: ExecutionAuthority,
        connection: MCPConnection,
    ) -> _ManagedConnection:
        for attempt in range(1, MCP_CONNECT_ATTEMPTS + 1):
            try:
                return await self._connect(authority, connection)
            except BaseException as exc:
                if attempt == MCP_CONNECT_ATTEMPTS or not _is_transient(exc):
                    raise
                logger.info(
                    "Retrying transient MCP connection failure",
                    data={
                        "event": "mcp_connection_retrying",
                        "connection_id": connection.connection_id,
                        "attempt": attempt + 1,
                        "error_type": type(exc).__name__,
                    },
                )
                await asyncio.sleep(0)
        raise RuntimeError("MCP connection retry loop exhausted unexpectedly.")

    def _lease(
        self,
        key: _ConnectionKey,
        entry: _ManagedConnection,
    ) -> MCPConnectionLease:
        return MCPConnectionLease(
            connection=entry.connection,
            client=entry.client,
            tools=entry.tools,
            release=lambda: self._release(key, entry),
        )

    async def _release(
        self,
        key: _ConnectionKey,
        entry: _ManagedConnection,
    ) -> None:
        close_entry = False
        async with self._state_lock:
            entry.active_leases = max(0, entry.active_leases - 1)
            entry.last_used = time.monotonic()
            if entry.invalidated and entry.active_leases == 0:
                close_entry = True
                if self._entries.get(key) is entry:
                    self._entries.pop(key, None)
        if close_entry:
            await _close_client(entry.client)

    async def _invalidate(self, principal_id: str, connection_id: str) -> None:
        to_close: list[_ManagedConnection] = []
        async with self._state_lock:
            for key, entry in list(self._entries.items()):
                if key[0] != principal_id or key[1] != connection_id:
                    continue
                entry.invalidated = True
                if entry.active_leases == 0:
                    self._entries.pop(key, None)
                    to_close.append(entry)
        await asyncio.gather(*(_close_client(entry.client) for entry in to_close))


def _key(
    authority: ExecutionAuthority,
    connection: MCPConnection,
) -> _ConnectionKey:
    return (
        authority.principal_id,
        connection.connection_id,
        connection.config_version,
    )


def _build_auth(
    connection: MCPConnection,
    credential: str | None,
    *,
    oauth_storage: EncryptedMCPOAuthStorage | None = None,
    allow_insecure_http: bool = False,
) -> tuple[dict[str, str] | None, str | httpx.Auth | None]:
    if connection.auth_mode is MCPAuthMode.BEARER:
        if credential is None:
            raise ValueError("MCP bearer credential is missing.")
        return None, credential
    if connection.auth_mode is MCPAuthMode.HEADER:
        if credential is None or connection.header_name is None:
            raise ValueError("MCP header credential is missing.")
        return {connection.header_name: credential}, None
    if connection.auth_mode is MCPAuthMode.OAUTH:
        if oauth_storage is None:
            raise ValueError("MCP OAuth storage is unavailable.")
        return None, ConnectedMCPOAuth(
            mcp_url=connection.url,
            token_storage=oauth_storage,
            allow_insecure_http=allow_insecure_http,
        )
    return None, None


def _mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    **_kwargs: object,
) -> httpx.AsyncClient:
    """Create a credential-safe client independent of ambient proxy settings."""
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout or httpx.Timeout(30.0, read=MCP_READ_TIMEOUT_SECONDS),
        auth=auth,
        follow_redirects=False,
        trust_env=False,
    )


class _CatalogChangeHandler(MessageHandler):
    def __init__(self, invalidate: Callable[[], None]) -> None:
        self._invalidate = invalidate

    async def on_tool_list_changed(
        self,
        message: ToolListChangedNotification,
    ) -> None:
        del message
        self._invalidate()


async def _close_client(client: Client) -> None:
    try:
        async with asyncio.timeout(MCP_CLOSE_TIMEOUT_SECONDS):
            await client.__aexit__(None, None, None)
    except (Exception, asyncio.CancelledError):
        logger.warning(
            "MCP client cleanup did not complete cleanly",
            data={"event": "mcp_client_cleanup_failed"},
        )


def _unavailable(
    connection: MCPConnection,
    error: BaseException,
) -> MCPUnavailableConnection:
    status = "connection_failed"
    message = "The MCP server did not become ready."
    if isinstance(error, TimeoutError | httpx.TimeoutException):
        status = "timeout"
        message = "The MCP server did not become ready before the timeout."
    elif isinstance(error, MCPNetworkPolicyError):
        status = "network_policy_rejected"
        message = str(error)
    elif isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {
        401,
        403,
    }:
        status = "authentication_failed"
        message = "The MCP server rejected authentication."
    elif isinstance(error, httpx.RequestError):
        status = "unreachable"
        message = "The MCP server could not be reached."
    logger.warning(
        "MCP connection unavailable",
        data={
            "event": "mcp_connection_unavailable",
            "connection_id": connection.connection_id,
            "url": sanitize_url_for_log(connection.url),
            "transport": connection.transport.value,
            "status": status,
            "error_type": type(error).__name__,
        },
    )
    return MCPUnavailableConnection(
        connection_id=connection.connection_id,
        display_name=connection.display_name,
        status=status,
        message=message,
    )


def _is_transient(error: BaseException) -> bool:
    return isinstance(error, TimeoutError | httpx.TimeoutException | httpx.RequestError)
