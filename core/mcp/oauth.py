"""Headless-safe interactive OAuth coordination for MCP connections."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
from fastmcp import Client
from fastmcp.client.auth import OAuth
from fastmcp.client.auth.oauth import TokenStorageAdapter
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.shared.auth import OAuthToken
from pydantic import AnyHttpUrl

from core.identity import ExecutionAuthority

from .manager import MCPConnectionManager
from .models import MCPAuthMode, MCPConnection, MCPTransport
from .oauth_storage import (
    EncryptedMCPOAuthStorage,
    mcp_oauth_http_client_factory,
)
from .service import MCPConnectionService

MCP_OAUTH_START_TIMEOUT_SECONDS = 15.0
MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS = 10 * 60.0
MCP_OAUTH_COMPLETE_TIMEOUT_SECONDS = 30.0
_PENDING_COLLECTION = "assistantmd"
_PENDING_KEY = "pending-authorization"


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
        allow_insecure_http: bool,
        scopes: tuple[str, ...] | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> None:
        self._authorization_url = authorization_url
        self._callback = callback
        self._storage = storage
        self._requested_scopes = scopes
        super().__init__(
            mcp_url=mcp_url,
            token_storage=storage,
            callback_timeout=MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS,
            httpx_client_factory=mcp_oauth_http_client_factory(
                allow_insecure_http=allow_insecure_http
            ),
            scopes=list(scopes) if scopes is not None else None,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.context.client_metadata.redirect_uris = [AnyHttpUrl(redirect_uri)]

    async def redirect_handler(self, authorization_url: str) -> None:
        if not self._authorization_url.done():
            self._authorization_url.set_result(authorization_url)

    async def callback_handler(self) -> tuple[str, str | None]:
        async with asyncio.timeout(MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS):
            return await self._callback

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        """Persist enough PKCE state to finish after a process restart."""
        if self._requested_scopes is not None:
            self.context.client_metadata.scope = " ".join(self._requested_scopes)
        if self.context.client_metadata.redirect_uris is None:
            raise OAuthFlowError("No redirect URI is configured.")
        if not self.context.client_info or not self.context.client_info.client_id:
            raise OAuthFlowError("No OAuth client registration is available.")
        if (
            self.context.oauth_metadata
            and self.context.oauth_metadata.authorization_endpoint
        ):
            auth_endpoint = str(self.context.oauth_metadata.authorization_endpoint)
        else:
            auth_endpoint = urljoin(
                self.context.get_authorization_base_url(self.context.server_url),
                "/authorize",
            )
        pkce = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)
        redirect_uri = str(self.context.client_metadata.redirect_uris[0])
        auth_params = {
            "response_type": "code",
            "client_id": self.context.client_info.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": pkce.code_challenge,
            "code_challenge_method": "S256",
        }
        resource: str | None = None
        if self.context.should_include_resource_param(self.context.protocol_version):
            resource = self.context.get_resource_url()
            auth_params["resource"] = resource
        if self.context.client_metadata.scope:
            auth_params["scope"] = self.context.client_metadata.scope
        authorization_url = f"{auth_endpoint}?{urlencode(auth_params)}"
        await self._storage.put(
            _PENDING_KEY,
            {
                "state": state,
                "code_verifier": pkce.code_verifier,
                "redirect_uri": redirect_uri,
                "token_endpoint": self._get_token_endpoint(),
                "client_id": self.context.client_info.client_id,
                "client_secret": self.context.client_info.client_secret,
                "token_endpoint_auth_method": (
                    self.context.client_info.token_endpoint_auth_method or "none"
                ),
                "resource": resource,
                "expires_at": (
                    datetime.now(UTC)
                    + timedelta(seconds=MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS)
                ).isoformat(),
            },
            collection=_PENDING_COLLECTION,
            ttl=MCP_OAUTH_CALLBACK_TIMEOUT_SECONDS,
        )
        await self.redirect_handler(authorization_url)
        auth_code, returned_state = await self.callback_handler()
        if returned_state is None or not secrets.compare_digest(returned_state, state):
            raise OAuthFlowError("OAuth state parameter mismatch.")
        if not auth_code:
            raise OAuthFlowError("No OAuth authorization code was received.")
        return auth_code, pkce.code_verifier


class MCPOAuthCoordinator:
    """Own process-local authorization attempts and encrypted durable tokens."""

    def __init__(
        self,
        *,
        connections: MCPConnectionService,
        manager: MCPConnectionManager,
        allow_insecure_http: bool = False,
    ) -> None:
        self._connections = connections
        self._manager = manager
        self._allow_insecure_http = allow_insecure_http
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
        await self._clear_pending(authority, connection)
        adapter = TokenStorageAdapter(
            async_key_value=self._connections.oauth_storage(authority, connection_id),
            server_url=connection.url,
        )
        await adapter.clear()
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
            await self._clear_pending(authority, connection)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, MCPOAuthError):
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
            connection = self._require_oauth_connection(authority, connection_id)
            await self._complete_persisted_attempt(
                authority=authority,
                connection=connection,
                code=code,
                state=state,
            )
            self._manager.invalidate(authority.principal_id, connection_id)
            return MCPOAuthStatus(status="connected", connected=True)
        if datetime.now(UTC) >= attempt.expires_at:
            await self._cancel_attempt(key)
            await self._clear_pending(authority, attempt.connection)
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
            await self._clear_pending(authority, attempt.connection)
            raise MCPOAuthError(
                "The MCP server did not complete OAuth authorization."
            ) from exc
        finally:
            async with self._lock:
                self._attempts.pop(key, None)
        await self._clear_pending(authority, attempt.connection)
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
        adapter = TokenStorageAdapter(
            async_key_value=self._connections.oauth_storage(authority, connection_id),
            server_url=connection.url,
        )
        connected = await adapter.get_tokens() is not None
        if not connected:
            pending = await self._load_pending(authority, connection)
            if pending is not None:
                return MCPOAuthStatus(
                    status="pending",
                    connected=False,
                    pending_expires_at=str(pending["expires_at"]),
                )
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
        await self._clear_pending(authority, connection)
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
            allow_insecure_http=self._allow_insecure_http,
            scopes=attempt.connection.oauth_scopes,
            client_id=attempt.connection.oauth_client_id,
            client_secret=self._connections.resolve_oauth_client_secret(
                attempt.authority, attempt.connection.connection_id
            ),
        )
        await _prime_oauth_authorization(auth, attempt.connection.url)
        http_client_factory = mcp_oauth_http_client_factory(
            allow_insecure_http=self._allow_insecure_http
        )
        transport = (
            StreamableHttpTransport(
                attempt.connection.url,
                auth=auth,
                httpx_client_factory=http_client_factory,
            )
            if attempt.connection.transport is MCPTransport.STREAMABLE_HTTP
            else SSETransport(
                attempt.connection.url,
                auth=auth,
                httpx_client_factory=http_client_factory,
            )
        )
        async with Client(transport, init_timeout=10.0, timeout=30.0):
            return

    async def _complete_persisted_attempt(
        self,
        *,
        authority: ExecutionAuthority,
        connection: MCPConnection,
        code: str,
        state: str,
    ) -> None:
        pending = await self._load_pending(authority, connection)
        if pending is None:
            raise MCPOAuthError("No active OAuth connection attempt was found.")
        expected_state = str(pending["state"])
        if not secrets.compare_digest(state, expected_state):
            raise MCPOAuthError("The MCP OAuth state did not match.")
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(pending["redirect_uri"]),
            "client_id": str(pending["client_id"]),
            "code_verifier": str(pending["code_verifier"]),
        }
        resource = pending.get("resource")
        if isinstance(resource, str) and resource:
            token_data["resource"] = resource
        auth: httpx.Auth | None = None
        method = str(pending["token_endpoint_auth_method"])
        client_secret = pending.get("client_secret")
        if method == "client_secret_post":
            if not isinstance(client_secret, str) or not client_secret:
                raise MCPOAuthError("Stored MCP OAuth client state is incomplete.")
            token_data["client_secret"] = client_secret
        elif method == "client_secret_basic":
            if not isinstance(client_secret, str) or not client_secret:
                raise MCPOAuthError("Stored MCP OAuth client state is incomplete.")
            auth = httpx.BasicAuth(str(pending["client_id"]), client_secret)
        elif method != "none":
            raise MCPOAuthError(
                "This MCP OAuth client authentication method is not supported."
            )
        try:
            http_client_factory = mcp_oauth_http_client_factory(
                allow_insecure_http=self._allow_insecure_http
            )
            async with http_client_factory(auth=auth) as client:
                response = await client.post(
                    str(pending["token_endpoint"]),
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            response.raise_for_status()
            tokens = OAuthToken.model_validate(response.json())
            adapter = TokenStorageAdapter(
                async_key_value=self._connections.oauth_storage(
                    authority, connection.connection_id
                ),
                server_url=connection.url,
            )
            await adapter.set_tokens(tokens)
        except (httpx.HTTPError, ValueError) as exc:
            raise MCPOAuthError(
                "The MCP server rejected OAuth completion. Start a new connection attempt."
            ) from exc
        finally:
            await self._clear_pending(authority, connection)

    async def _load_pending(
        self, authority: ExecutionAuthority, connection: MCPConnection
    ) -> dict[str, Any] | None:
        storage = self._connections.oauth_storage(authority, connection.connection_id)
        pending = await storage.get(_PENDING_KEY, collection=_PENDING_COLLECTION)
        if pending is None:
            return None
        required = {
            "state",
            "code_verifier",
            "redirect_uri",
            "token_endpoint",
            "client_id",
            "token_endpoint_auth_method",
            "expires_at",
        }
        if not required.issubset(pending):
            await self._clear_pending(authority, connection)
            raise MCPOAuthError("Stored MCP OAuth pending state is invalid.")
        try:
            expires_at = datetime.fromisoformat(str(pending["expires_at"]))
        except ValueError as exc:
            await self._clear_pending(authority, connection)
            raise MCPOAuthError("Stored MCP OAuth pending state is invalid.") from exc
        if expires_at.tzinfo is None or datetime.now(UTC) >= expires_at:
            await self._clear_pending(authority, connection)
            return None
        return pending

    async def _clear_pending(
        self, authority: ExecutionAuthority, connection: MCPConnection
    ) -> None:
        await self._connections.oauth_storage(
            authority, connection.connection_id
        ).delete(_PENDING_KEY, collection=_PENDING_COLLECTION)

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


async def _prime_oauth_authorization(auth: _HeadlessOAuth, mcp_url: str) -> None:
    """Start standards discovery even when MCP initialization is public."""
    request = httpx.Request("GET", mcp_url)
    flow = auth.async_auth_flow(request)
    try:
        await anext(flow)
        response = httpx.Response(401, request=request)
        async with auth.httpx_client_factory() as client:
            while True:
                next_request = await flow.asend(response)
                if (
                    auth.context.oauth_metadata is not None
                    and auth.context.oauth_metadata.registration_endpoint is None
                    and auth.context.client_info is None
                ):
                    raise MCPOAuthError(
                        "This MCP server requires a pre-registered OAuth client ID "
                        "and client secret. Save them in the connection before "
                        "authorizing."
                    )
                if (
                    auth._authorization_url.done()
                    and next_request.url == request.url
                    and "Authorization" in next_request.headers
                ):
                    return
                response = await client.send(next_request)
    except StopAsyncIteration:
        return
    finally:
        await flow.aclose()
