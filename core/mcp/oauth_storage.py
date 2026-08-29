"""Encrypted principal-owned key-value storage for FastMCP OAuth state."""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.client.auth import OAuth
from fastmcp.client.auth.oauth import TokenStorageAdapter
from mcp.shared._httpx_utils import McpHttpClientFactory

from core.identity import ExecutionAuthority
from core.oauth import EncryptedOAuthStorage
from core.secrets import EncryptedSecretsService, SecretIdentity

from .network import MCPAsyncHTTPTransport, validate_mcp_endpoint

_OAUTH_NAMESPACE_SUFFIX = ".oauth"
MCP_OAUTH_FENCE_NAME = "oauth_fence_token"


class EncryptedMCPOAuthStorage(EncryptedOAuthStorage):
    """Implement FastMCP's async KV contract over encrypted secret records."""

    def __init__(
        self,
        *,
        secrets: EncryptedSecretsService,
        authority: ExecutionAuthority,
        connection_id: str,
        fence_token: str,
    ) -> None:
        namespace = f"mcp.connection.{connection_id}"
        super().__init__(
            secrets=secrets,
            authority=authority,
            namespace=f"{namespace}{_OAUTH_NAMESPACE_SUFFIX}",
            write_guard=(
                SecretIdentity(namespace=namespace, name=MCP_OAUTH_FENCE_NAME),
                fence_token,
            ),
        )


class ConnectedMCPOAuth(OAuth):
    """Use stored OAuth state without starting an interactive browser flow."""

    def __init__(
        self,
        *,
        mcp_url: str,
        token_storage: EncryptedMCPOAuthStorage,
        allow_private_http: bool,
    ) -> None:
        super().__init__(
            mcp_url=mcp_url,
            token_storage=token_storage,
            httpx_client_factory=mcp_oauth_http_client_factory(
                allow_private_http=allow_private_http
            ),
        )

    async def redirect_handler(self, authorization_url: str) -> None:
        del authorization_url
        raise ValueError(
            "MCP OAuth authorization is required. Connect this server in System."
        )

    async def callback_handler(self) -> tuple[str, str | None]:
        raise ValueError(
            "MCP OAuth authorization is required. Connect this server in System."
        )


async def has_mcp_oauth_tokens(
    *, storage: EncryptedMCPOAuthStorage, mcp_url: str
) -> bool:
    """Return whether FastMCP has persisted tokens for this server URL."""
    adapter = TokenStorageAdapter(async_key_value=storage, server_url=mcp_url)
    return await adapter.get_tokens() is not None


def _oauth_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create an OAuth client that cannot inherit proxies or follow redirects."""
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
        trust_env=False,
    )


def mcp_oauth_http_client_factory(*, allow_private_http: bool) -> McpHttpClientFactory:
    """Create clients that validate every MCP/OAuth request immediately before use."""

    async def validate_request(request: httpx.Request) -> None:
        await validate_mcp_endpoint(
            str(request.url),
            allow_private_http=allow_private_http,
        )

    def create_client(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        **_kwargs: Any,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [validate_request]},
            transport=MCPAsyncHTTPTransport(),
        )

    return create_client
