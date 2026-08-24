"""Headless-safe interactive OAuth coordination for MCP connections."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastmcp import Client
from fastmcp.client.auth import OAuth
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from pydantic import AnyHttpUrl

from core.identity import ExecutionAuthority

from .manager import MCPConnectionManager
from .models import MCPAuthMode, MCPConnection, MCPTransport
from .oauth_storage import EncryptedMCPOAuthStorage, _oauth_http_client
from .service import MCPConnectionService

MCP_OAUTH_START_TIMEOUT_SECONDS = 15.0
MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS = 10 * 60.0
MCP_OAUTH_COMPLETE_TIMEOUT_SECONDS = 30.0


class MCPOAuthError(ValueError):
    """Raised for sanitized, user-correctable MCP OAuth failures."""


@dataclass(frozen=True)
class MCPOAuthStart:
    auth_url: str
    state: str
    redirect_uri: str
    expires_at: str


@dataclass(frozen=True)
class MCPOAuthStatus:
    status: str
    connected: bool
    pending_expires_at: str | None = None


@dataclass
class _Attempt:
    authority: ExecutionAuthority
    connection: MCPConnection
    redirect_uri: str
    authorization_url: asyncio.Future[str]
    callback: asyncio.Future[tuple[str, str | None]]
    task: asyncio.Task[None] | None
    expires_at: datetime


class _HeadlessOAuth(OAuth):
    def __init__(
        self,
        *,
        mcp_url: str,
        redirect_uri: str,
        storage: EncryptedMCPOAuthStorage,
        authorization_url: asyncio.Future[str],
        callback: asyncio.Future[tuple[str, str | None]],
    ) -> None:
        self._authorization_url = authorization_url
        self._callback = callback
        super().__init__(
            mcp_url=mcp_url,
            token_storage=storage,
            callback_timeout=MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS,
            httpx_client_factory=_oauth_http_client,
        )
        self.context.client_metadata.redirect_uris = [AnyHttpUrl(redirect_uri)]

    async def redirect_handler(self, authorization_url: str) -> None:
        if not self._authorization_url.done():
            self._authorization_url.set_result(authorization_url)

    async def callback_handler(self) -> tuple[str, str | None]:
        async with asyncio.timeout(MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS):
            return await self._callback


class MCPOAuthCoordinator:
    """Own process-local authorization attempts and encrypted durable tokens."""

    def __init__(
        self,
        *,
        connections: MCPConnectionService,
        manager: MCPConnectionManager,
    ) -> None:
        self._connections = connections
        self._manager = manager
        self._attempts: dict[tuple[str, str], _Attempt] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        authority: ExecutionAuthority,
        connection_id: str,
        redirect_uri: str,
    ) -> MCPOAuthStart:
        connection = self._require_oauth_connection(authority, connection_id)
        clean_redirect_uri = _validate_redirect_uri(redirect_uri)
        key = (authority.principal_id, connection.connection_id)
        await self._cancel_attempt(key)
        loop = asyncio.get_running_loop()
        attempt = _Attempt(
            authority=authority,
            connection=connection,
            redirect_uri=clean_redirect_uri,
            authorization_url=loop.create_future(),
            callback=loop.create_future(),
            task=None,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS),
        )
        async with self._lock:
            self._attempts[key] = attempt
        task = asyncio.create_task(self._run_attempt(attempt))
        attempt.task = task
        try:
            wait_set: set[asyncio.Future[Any]] = {attempt.authorization_url, task}
            done, _ = await asyncio.wait(
                wait_set,
                timeout=MCP_OAUTH_START_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if attempt.authorization_url in done:
                auth_url = attempt.authorization_url.result()
            elif task in done:
                task.result()
                raise MCPOAuthError(
                    "The MCP server completed without requesting OAuth authorization."
                )
            else:
                raise TimeoutError
        except BaseException as exc:
            await self._cancel_attempt(key)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise MCPOAuthError(
                "The MCP server did not start an OAuth authorization flow."
            ) from exc
        state = _required_query_value(auth_url, "state")
        return MCPOAuthStart(
            auth_url=auth_url,
            state=state,
            redirect_uri=clean_redirect_uri,
            expires_at=attempt.expires_at.isoformat(),
        )

    async def complete(
        self,
        *,
        authority: ExecutionAuthority,
        connection_id: str,
        code: str,
        state: str,
    ) -> MCPOAuthStatus:
        key = (authority.principal_id, connection_id)
        async with self._lock:
            attempt = self._attempts.get(key)
        if attempt is None or attempt.task is None:
            raise MCPOAuthError("No active OAuth connection attempt was found.")
        if datetime.now(UTC) >= attempt.expires_at:
            await self._cancel_attempt(key)
            raise MCPOAuthError("The MCP OAuth connection attempt has expired.")
        expected_state = _required_query_value(
            await asyncio.shield(attempt.authorization_url), "state"
        )
        if not secrets.compare_digest(state, expected_state):
            raise MCPOAuthError("The MCP OAuth state did not match.")
        if not attempt.callback.done():
            attempt.callback.set_result((code, state))
        try:
            await asyncio.wait_for(
                asyncio.shield(attempt.task),
                timeout=MCP_OAUTH_COMPLETE_TIMEOUT_SECONDS,
            )
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            await self._cancel_attempt(key)
            raise MCPOAuthError(
                "The MCP server did not complete OAuth authorization."
            ) from exc
        finally:
            async with self._lock:
                self._attempts.pop(key, None)
        self._manager.invalidate(authority.principal_id, connection_id)
        return MCPOAuthStatus(status="connected", connected=True)

    async def status(
        self, *, authority: ExecutionAuthority, connection_id: str
    ) -> MCPOAuthStatus:
        connection = self._require_oauth_connection(authority, connection_id)
        key = (authority.principal_id, connection.connection_id)
        async with self._lock:
            attempt = self._attempts.get(key)
        if attempt is not None and datetime.now(UTC) < attempt.expires_at:
            if attempt.task is not None and attempt.task.done():
                try:
                    attempt.task.result()
                except BaseException:
                    await self._cancel_attempt(key)
                    return MCPOAuthStatus(status="failed", connected=False)
            return MCPOAuthStatus(
                status="pending",
                connected=False,
                pending_expires_at=attempt.expires_at.isoformat(),
            )
        if attempt is not None:
            await self._cancel_attempt(key)
        from fastmcp.client.auth.oauth import TokenStorageAdapter

        adapter = TokenStorageAdapter(
            async_key_value=self._connections.oauth_storage(authority, connection_id),
            server_url=connection.url,
        )
        connected = await adapter.get_tokens() is not None
        return MCPOAuthStatus(
            status="connected" if connected else "disconnected",
            connected=connected,
        )

    async def disconnect(
        self, *, authority: ExecutionAuthority, connection_id: str
    ) -> None:
        connection = self._require_oauth_connection(authority, connection_id)
        key = (authority.principal_id, connection.connection_id)
        await self._cancel_attempt(key)
        from fastmcp.client.auth.oauth import TokenStorageAdapter

        adapter = TokenStorageAdapter(
            async_key_value=self._connections.oauth_storage(authority, connection_id),
            server_url=connection.url,
        )
        await adapter.clear()
        self._manager.invalidate(authority.principal_id, connection_id)

    async def shutdown(self) -> None:
        async with self._lock:
            keys = tuple(self._attempts)
        await asyncio.gather(*(self._cancel_attempt(key) for key in keys))

    async def _run_attempt(self, attempt: _Attempt) -> None:
        storage = self._connections.oauth_storage(
            attempt.authority, attempt.connection.connection_id
        )
        auth = _HeadlessOAuth(
            mcp_url=attempt.connection.url,
            redirect_uri=attempt.redirect_uri,
            storage=storage,
            authorization_url=attempt.authorization_url,
            callback=attempt.callback,
        )
        transport = (
            StreamableHttpTransport(
                attempt.connection.url,
                auth=auth,
                httpx_client_factory=_oauth_http_client,
            )
            if attempt.connection.transport is MCPTransport.STREAMABLE_HTTP
            else SSETransport(
                attempt.connection.url,
                auth=auth,
                httpx_client_factory=_oauth_http_client,
            )
        )
        async with Client(transport, init_timeout=10.0, timeout=30.0):
            return

    async def _cancel_attempt(self, key: tuple[str, str]) -> None:
        async with self._lock:
            attempt = self._attempts.pop(key, None)
        if attempt is None:
            return
        if not attempt.callback.done():
            attempt.callback.cancel()
        if attempt.task is not None and not attempt.task.done():
            attempt.task.cancel()
            await asyncio.gather(attempt.task, return_exceptions=True)

    def _require_oauth_connection(
        self, authority: ExecutionAuthority, connection_id: str
    ) -> MCPConnection:
        connection = self._connections.get_connection_for_authority(
            authority, connection_id
        )
        if connection is None:
            raise LookupError("MCP connection not found.")
        if connection.auth_mode is not MCPAuthMode.OAUTH:
            raise MCPOAuthError("This MCP connection is not configured for OAuth.")
        return connection


def parse_oauth_completion(
    *, redirect_url: str | None, code: str | None, state: str | None
) -> tuple[str, str]:
    if redirect_url:
        parsed = urlparse(redirect_url)
        query = parse_qs(parsed.query)
        code = _single_query_value(query, "code")
        state = _single_query_value(query, "state")
    if not code or not state:
        raise MCPOAuthError("MCP OAuth completion requires both code and state.")
    return code, state


def _validate_redirect_uri(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MCPOAuthError("MCP OAuth redirect URI must be an absolute HTTP URL.")
    if parsed.username or parsed.password or parsed.fragment:
        raise MCPOAuthError("MCP OAuth redirect URI is invalid.")
    return parsed.geturl()


def _required_query_value(url: str, key: str) -> str:
    value = _single_query_value(parse_qs(urlparse(url).query), key)
    if value is None:
        raise MCPOAuthError(f"MCP OAuth authorization URL omitted {key}.")
    return value


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key, [])
    return values[0] if len(values) == 1 and values[0] else None
