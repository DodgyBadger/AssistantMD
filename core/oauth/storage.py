"""Encrypted principal-owned key/value storage for OAuth state."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, SupportsFloat

from core.identity import ExecutionAuthority
from core.secrets import (
    EncryptedSecretsService,
    SecretIdentity,
    SecretRelocation,
)


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
        write_guard: tuple[SecretIdentity, str] | None = None,
    ) -> None:
        clean_namespace = str(namespace or "").strip()
        if not clean_namespace:
            raise ValueError("OAuth storage namespace cannot be empty.")
        self._secrets = secrets
        self._authority = authority
        self._namespace = clean_namespace
        self._write_guard = write_guard

    async def get(
        self, key: str, *, collection: str | None = None
    ) -> dict[str, Any] | None:
        return self.get_sync(key, collection=collection)

    def get_sync(
        self, key: str, *, collection: str | None = None
    ) -> dict[str, Any] | None:
        """Read OAuth JSON from synchronous service boundaries."""
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
        self.put_sync(key, value, collection=collection, ttl=ttl)

    def put_sync(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        """Write OAuth JSON from synchronous service boundaries."""
        expires_at = time.time() + float(ttl) if ttl is not None else None
        payload = _encode_stored_value(value, expires_at=expires_at)
        target = self._identity(key, collection)
        if self._write_guard is None:
            self._secrets.set_for_authority(
                self._authority,
                target.namespace,
                target.name,
                payload,
            )
        else:
            guard, expected_value = self._write_guard
            self._secrets.guarded_set_for_authority(
                self._authority,
                guard=guard,
                expected_guard_value=expected_value,
                target=target,
                value=payload,
            )

    def put_sync_if_unchanged(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        guard_key: str,
        expected_guard_value: Mapping[str, Any],
        collection: str | None = None,
        guard_collection: str | None = None,
        additional_guard_key: str | None = None,
        additional_expected_guard_value: Mapping[str, Any] | None = None,
    ) -> None:
        """Write only while another non-expiring OAuth value is unchanged."""
        target = self._identity(key, collection)
        guard = self._identity(guard_key, guard_collection)
        payload = _encode_stored_value(value, expires_at=None)
        expected_payload = _encode_stored_value(
            expected_guard_value,
            expires_at=None,
        )
        additional_guards: tuple[tuple[SecretIdentity, str], ...] = ()
        if (additional_guard_key is None) != (additional_expected_guard_value is None):
            raise ValueError("Additional OAuth guard key and value must be paired.")
        if (
            additional_guard_key is not None
            and additional_expected_guard_value is not None
        ):
            additional_guards = (
                (
                    self._identity(additional_guard_key, collection),
                    _encode_stored_value(
                        additional_expected_guard_value,
                        expires_at=None,
                    ),
                ),
            )
        self._secrets.guarded_set_for_authority(
            self._authority,
            guard=guard,
            expected_guard_value=expected_payload,
            target=target,
            value=payload,
            additional_guards=additional_guards,
        )

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        return self.delete_sync(key, collection=collection)

    def delete_sync(self, key: str, *, collection: str | None = None) -> bool:
        """Delete OAuth JSON from synchronous service boundaries."""
        target = self._identity(key, collection)
        existed = self._secrets.get_for_authority(
            self._authority, target.namespace, target.name
        )
        if self._write_guard is None:
            self._secrets.delete_for_authority(
                self._authority, target.namespace, target.name
            )
        else:
            guard, expected_value = self._write_guard
            self._secrets.guarded_delete_for_authority(
                self._authority,
                guard=guard,
                expected_guard_value=expected_value,
                target=target,
            )
        return existed is not None

    def delete_sync_if_unchanged(
        self,
        key: str,
        expected_value: Mapping[str, Any],
        *,
        collection: str | None = None,
    ) -> bool:
        """Delete one OAuth value only if its exact payload is unchanged."""
        target = self._identity(key, collection)
        return self._secrets.guarded_delete_for_authority(
            self._authority,
            guard=target,
            expected_guard_value=_encode_stored_value(
                expected_value,
                expires_at=None,
            ),
            target=target,
        )

    def relocate_sync(
        self,
        key: str,
        *,
        destination: EncryptedOAuthStorage,
        collection: str | None = None,
        overwrite: bool = False,
    ) -> bool:
        """Move one OAuth entry atomically without exposing its hashed identity."""
        self._require_compatible_storage(destination)
        result = self._secrets.mutate_for_authority(
            self._authority,
            relocations=(
                SecretRelocation(
                    source=self._identity(key, collection),
                    destination=destination._identity(key, collection),
                    overwrite=overwrite,
                ),
            ),
        )
        return result.relocated_count == 1

    def delete_many_sync(
        self,
        keys: Sequence[str],
        *,
        collection: str | None = None,
        additional_storages: Sequence[EncryptedOAuthStorage] = (),
    ) -> int:
        """Delete entries across compatible OAuth namespaces atomically."""
        storages = (self, *additional_storages)
        for storage in storages[1:]:
            self._require_compatible_storage(storage)
        identities = tuple(
            storage._identity(key, collection) for storage in storages for key in keys
        )
        return self._secrets.mutate_for_authority(
            self._authority,
            deletions=identities,
        ).deleted_count

    def replace_and_delete_sync(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        delete_keys: Sequence[str],
        collection: str | None = None,
        expected_value: Mapping[str, Any] | None = None,
    ) -> int:
        """Replace one non-expiring value and delete related entries atomically."""
        payload = _encode_stored_value(value, expires_at=None)
        return self._secrets.replace_and_delete_for_authority(
            self._authority,
            target=self._identity(key, collection),
            value=payload,
            deletions=tuple(
                self._identity(delete_key, collection) for delete_key in delete_keys
            ),
            expected_value=(
                _encode_stored_value(expected_value, expires_at=None)
                if expected_value is not None
                else None
            ),
        )

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
            if self._write_guard is None:
                self._secrets.delete_for_authority(
                    self._authority, self._namespace, name
                )
            else:
                guard, expected_value = self._write_guard
                self._secrets.guarded_delete_for_authority(
                    self._authority,
                    guard=guard,
                    expected_guard_value=expected_value,
                    target=SecretIdentity(namespace=self._namespace, name=name),
                )
            return None
        return _StoredValue(value=value, expires_at=expires_at)

    def _identity(self, key: str, collection: str | None) -> SecretIdentity:
        return SecretIdentity(
            namespace=self._namespace,
            name=_storage_name(key, collection),
        )

    def _require_compatible_storage(self, other: EncryptedOAuthStorage) -> None:
        if self._secrets is not other._secrets or self._authority != other._authority:
            raise ValueError(
                "OAuth storage mutation requires one service and authority."
            )


def _encode_stored_value(value: Mapping[str, Any], *, expires_at: float | None) -> str:
    return json.dumps(
        {"value": dict(value), "expires_at": expires_at},
        separators=(",", ":"),
        sort_keys=True,
    )


def _storage_name(key: str, collection: str | None) -> str:
    """Map arbitrary OAuth keys to stable non-sensitive secret names."""
    identity = f"{collection or ''}\0{key}".encode()
    return hashlib.sha256(identity).hexdigest()
