"""Encrypted principal-owned key/value storage for OAuth state."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, SupportsFloat

from core.identity import ExecutionAuthority
from core.secrets import EncryptedSecretsService


@dataclass(frozen=True)
class _StoredValue:
    value: dict[str, Any]
    expires_at: float | None


class EncryptedOAuthStorage:
    """Store expiring OAuth JSON records under an explicit authority/namespace."""

    def __init__(
        self,
        *,
        secrets: EncryptedSecretsService,
        authority: ExecutionAuthority,
        namespace: str,
    ) -> None:
        clean_namespace = str(namespace or "").strip()
        if not clean_namespace:
            raise ValueError("OAuth storage namespace cannot be empty.")
        self._secrets = secrets
        self._authority = authority
        self._namespace = clean_namespace

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
            raise ValueError("Stored OAuth state is invalid.") from exc
        if expires_at is not None and expires_at <= time.time():
            self._secrets.delete_for_authority(self._authority, self._namespace, name)
            return None
        return _StoredValue(value=value, expires_at=expires_at)


def _storage_name(key: str, collection: str | None) -> str:
    """Map arbitrary OAuth keys to stable non-sensitive secret names."""
    identity = f"{collection or ''}\0{key}".encode()
    return hashlib.sha256(identity).hexdigest()
