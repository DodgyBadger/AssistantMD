"""Stable vault identity helpers for vault-state storage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from core.constants import ASSISTANTMD_ROOT_DIR


VAULT_METADATA_RELATIVE_PATH = Path(ASSISTANTMD_ROOT_DIR) / "vault.yaml"


@dataclass(frozen=True)
class VaultIdentity:
    """Resolved stable vault identity."""

    vault_id: str
    metadata_path: Path
    created: bool


def resolve_or_create_vault_identity(vault_path: Path) -> VaultIdentity:
    """Return a stable vault id stored inside the vault."""
    metadata_path = vault_path / VAULT_METADATA_RELATIVE_PATH
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
    metadata_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return VaultIdentity(vault_id=vault_id, metadata_path=metadata_path, created=True)


def _load_metadata(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Vault metadata must be a mapping: {path}")
    return raw
