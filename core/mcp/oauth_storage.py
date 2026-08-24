"""Encrypted principal-owned key-value storage for FastMCP OAuth state."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, SupportsFloat

import httpx
from fastmcp.client.auth import OAuth
from fastmcp.client.auth.oauth import TokenStorageAdapter
from mcp.shared._httpx_utils import McpHttpClientFactory

from core.identity import ExecutionAuthority
from core.secrets import EncryptedSecretsService

from .network import validate_mcp_endpoint

_OAUTH_NAMESPACE_SUFFIX = ".oauth"


@dataclass(frozen=True)
class _StoredValue:
    value: dict[str, Any]
    expires_at: float | None


class EncryptedMCPOAuthStorage:
    """Implement FastMCP's async KV contract over encrypted secret records."""

    def __init__(
        self,
        *,
        secrets: EncryptedSecretsService,
        authority: ExecutionAuthority,
        connection_id: str,
    ) -> None:
        self._secrets = secrets
        self._authority = authority
        self._namespace = f"mcp.connection.{connection_id}{_OAUTH_NAMESPACE_SUFFIX}"

    async def get(
        self, key: str, *, collection: str | None = None
    ) -> dict[str, Any] | None:
        stored = self._load(key, collection=collection)
        return stored.value if stored is not None else None

    async def ttl(
        self, key: str, *, collection: str | None = None
    ) -> tuple[dict[str, Any] | None, float | None]:
        stored = self._load(key, collection=collection)
        if stored is None:
            return None, None
        remaining = (
            max(stored.expires_at - time.time(), 0.0)
            if stored.expires_at is not None
            else None
        )
        return stored.value, remaining

    async def put(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        expires_at = time.time() + float(ttl) if ttl is not None else None
        payload = json.dumps(
            {"value": dict(value), "expires_at": expires_at},
            separators=(",", ":"),
            sort_keys=True,
        )
        self._secrets.set_for_authority(
            self._authority,
            self._namespace,
            _storage_name(key, collection),
            payload,
        )

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        name = _storage_name(key, collection)
        existed = self._secrets.get_for_authority(
            self._authority, self._namespace, name
        )
        self._secrets.delete_for_authority(self._authority, self._namespace, name)
        return existed is not None

    async def get_many(
        self, keys: Sequence[str], *, collection: str | None = None
    ) -> list[dict[str, Any] | None]:
        return [await self.get(key, collection=collection) for key in keys]

    async def ttl_many(
        self, keys: Sequence[str], *, collection: str | None = None
    ) -> list[tuple[dict[str, Any] | None, float | None]]:
        return [await self.ttl(key, collection=collection) for key in keys]

    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        if len(keys) != len(values):
            raise ValueError("OAuth storage keys and values must have equal lengths.")
        for key, value in zip(keys, values, strict=True):
            await self.put(key, value, collection=collection, ttl=ttl)

    async def delete_many(
        self, keys: Sequence[str], *, collection: str | None = None
    ) -> int:
        removed = 0
        for key in keys:
            removed += int(await self.delete(key, collection=collection))
        return removed

    def _load(self, key: str, *, collection: str | None) -> _StoredValue | None:
        name = _storage_name(key, collection)
        payload = self._secrets.get_for_authority(
            self._authority, self._namespace, name
        )
        if payload is None:
            return None
        try:
            parsed = json.loads(payload)
            value = parsed["value"]
            expires_at = parsed.get("expires_at")
            if not isinstance(value, dict):
                raise TypeError
            if expires_at is not None and not isinstance(expires_at, int | float):
                raise TypeError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Stored MCP OAuth state is invalid.") from exc
        if expires_at is not None and expires_at <= time.time():
            self._secrets.delete_for_authority(self._authority, self._namespace, name)
            return None
        return _StoredValue(value=value, expires_at=expires_at)


class ConnectedMCPOAuth(OAuth):
    """Use stored OAuth state without starting an interactive browser flow."""

    def __init__(
        self,
        *,
        mcp_url: str,
        token_storage: EncryptedMCPOAuthStorage,
        allow_insecure_http: bool,
    ) -> None:
        super().__init__(
            mcp_url=mcp_url,
            token_storage=token_storage,
            httpx_client_factory=mcp_oauth_http_client_factory(
                allow_insecure_http=allow_insecure_http
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


def _storage_name(key: str, collection: str | None) -> str:
    """Map arbitrary FastMCP keys to stable non-sensitive secret names."""
    identity = f"{collection or ''}\0{key}".encode()
    return hashlib.sha256(identity).hexdigest()


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


def mcp_oauth_http_client_factory(*, allow_insecure_http: bool) -> McpHttpClientFactory:
    """Create clients that validate every MCP/OAuth request immediately before use."""

    async def validate_request(request: httpx.Request) -> None:
        await validate_mcp_endpoint(
            str(request.url),
            allow_insecure_http=allow_insecure_http,
        )

    def create_client(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [validate_request]},
        )

    return create_client
