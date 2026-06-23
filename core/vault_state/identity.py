"""Stable vault identity helpers for vault-state storage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import sleep
from typing import Any

import yaml

from core.constants import ASSISTANTMD_ROOT_DIR


VAULT_METADATA_RELATIVE_PATH = Path(ASSISTANTMD_ROOT_DIR) / "vault.yaml"
_COLLISION_LOAD_ATTEMPTS = 5
_COLLISION_LOAD_DELAY_SECONDS = 0.01
_IDENTITY_LOCKS: dict[Path, Lock] = {}
_IDENTITY_LOCKS_GUARD = Lock()


@dataclass(frozen=True)
class VaultIdentity:
    """Resolved stable vault identity."""

    vault_id: str
    metadata_path: Path
    created: bool


def resolve_or_create_vault_identity(vault_path: Path) -> VaultIdentity:
    """Return a stable vault id stored inside the vault."""
    vault_root = Path(vault_path).resolve()
    metadata_path = vault_root / VAULT_METADATA_RELATIVE_PATH
    lock = _identity_lock(vault_root)
    with lock:
        return _resolve_or_create_locked(metadata_path)


def _resolve_or_create_locked(metadata_path: Path) -> VaultIdentity:
    """Resolve or create vault metadata while the per-vault lock is held."""
    if metadata_path.exists():
        payload = _load_metadata(metadata_path)
        vault_id = str(payload.get("vault_id", "")).strip()
        if not vault_id:
            raise ValueError(f"Vault metadata is missing vault_id: {metadata_path}")
        return VaultIdentity(vault_id=vault_id, metadata_path=metadata_path, created=False)

    vault_id = f"vault_{uuid.uuid4().hex}"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "vault_id": vault_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    try:
        with metadata_path.open("x", encoding="utf-8") as handle:
            handle.write(yaml.safe_dump(payload, sort_keys=False))
    except FileExistsError:
        return _load_metadata_after_collision(metadata_path)
    return VaultIdentity(vault_id=vault_id, metadata_path=metadata_path, created=True)


def _identity_lock(vault_path: Path) -> Lock:
    """Return the process-local lock for one resolved vault path."""
    with _IDENTITY_LOCKS_GUARD:
        lock = _IDENTITY_LOCKS.get(vault_path)
        if lock is None:
            lock = Lock()
            _IDENTITY_LOCKS[vault_path] = lock
        return lock


def _load_metadata_after_collision(metadata_path: Path) -> VaultIdentity:
    """Load vault metadata that another caller just created."""
    last_error: Exception | None = None
    for attempt in range(_COLLISION_LOAD_ATTEMPTS):
        try:
            payload = _load_metadata(metadata_path)
            existing_vault_id = str(payload.get("vault_id", "")).strip()
            if not existing_vault_id:
                raise ValueError(f"Vault metadata is missing vault_id: {metadata_path}")
            return VaultIdentity(
                vault_id=existing_vault_id,
                metadata_path=metadata_path,
                created=False,
            )
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            last_error = exc
            if attempt + 1 < _COLLISION_LOAD_ATTEMPTS:
                sleep(_COLLISION_LOAD_DELAY_SECONDS)

    raise ValueError(
        f"Vault metadata could not be read after concurrent creation: {metadata_path}"
    ) from last_error


def _load_metadata(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Vault metadata must be a mapping: {path}")
    return raw
