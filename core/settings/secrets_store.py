"""
Secrets store utilities.

Provides a hot-reloadable YAML-backed storage layer for API keys and other
confidential values. Replaces the legacy .env handling so secrets can be
managed independently from infrastructure configuration.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from collections import OrderedDict

import yaml

from core.runtime.paths import get_system_root


SECRETS_PATH_ENV = "SECRETS_PATH"
SECRETS_BASE_PATH_ENV = "SECRETS_BASE_PATH"
SECRETS_TEMPLATE = Path(__file__).parent / "secrets.template.yaml"


class _SecretsDumper(yaml.SafeDumper):
    """Custom YAML dumper that renders None values as empty strings."""


def _represent_none(self, _):  # type: ignore[override]
    return self.represent_scalar("tag:yaml.org,2002:null", "")


_SecretsDumper.add_representer(type(None), _represent_none)


@dataclass(frozen=True)
class SecretEntry:
    """Metadata about a stored secret without exposing values."""

    name: str
    has_value: bool
    is_overlay: bool = False


def _resolve_system_root() -> Path:
    """
    Determine the active system root, preferring runtime context over defaults.

    Falls back to environment/default constants when a runtime context has not
    been established (e.g. before bootstrap).
    """
    return get_system_root()


def _resolve_secrets_path() -> Path:
    """Determine the active secrets file path."""
    override = os.environ.get(SECRETS_PATH_ENV)
    if override:
        return Path(override)
    return _resolve_system_root() / "secrets.yaml"


def _resolve_base_secrets_path() -> Optional[Path]:
    """Optional base secrets path used for read-only fallbacks."""
    base_override = os.environ.get(SECRETS_BASE_PATH_ENV)
    if base_override:
        return Path(base_override)
    default_base = _resolve_system_root() / "secrets.yaml"
    return default_base if default_base.exists() else None


def _ensure_file(path: Path) -> None:
    """Ensure the secrets file exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        if SECRETS_TEMPLATE.exists():
            shutil.copyfile(SECRETS_TEMPLATE, path)
        else:
            path.write_text("", encoding="utf-8")


def _read_raw(path: Path, include_empty: bool = False) -> "OrderedDict[str, Optional[str]]":
    """Read raw secrets mapping from disk."""
    _ensure_file(path)
    raw_text = path.read_text(encoding="utf-8")
    if not raw_text.strip():
        return OrderedDict()

    data = yaml.safe_load(raw_text) or {}
    if not isinstance(data, dict):
        raise ValueError("Secrets file must contain a mapping of key/value pairs.")

    normalized: "OrderedDict[str, Optional[str]]" = OrderedDict()
    for key, value in data.items():
        if not isinstance(key, str):
            raise ValueError("Secret names must be strings.")
        if value is None or (isinstance(value, str) and not value.strip()):
            if include_empty:
                normalized[key] = None
            continue
        if not isinstance(value, str):
            raise ValueError(f"Secret '{key}' must be stored as a string.")
        normalized[key] = value
    return normalized


def _write_raw(path: Path, data: Dict[str, Optional[str]]) -> None:
    """Persist secrets mapping to disk using an atomic write."""
    _ensure_file(path)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        if data:
            serializable = dict(data)
            yaml.dump(
                serializable,
                handle,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=False,
                Dumper=_SecretsDumper,
            )
        else:
            handle.write("")
    os.replace(tmp_path, path)


def load_secrets(include_empty: bool = False) -> Dict[str, str]:
    """
    Load all secrets from disk, merging overlay and optional base store.

    Args:
        include_empty: When True, include keys that exist with empty values.

    Returns:
        Dictionary mapping secret names to values.
    """
    overlay_path = _resolve_secrets_path()
    overlay = _read_raw(overlay_path, include_empty=include_empty)

    base_path = _resolve_base_secrets_path()
    base = (
        _read_raw(base_path, include_empty=include_empty)
        if base_path and base_path.exists() and base_path != overlay_path
        else OrderedDict()
    )

    merged: "OrderedDict[str, Optional[str]]" = OrderedDict()
    merged.update(base)
    merged.update(overlay)

    if include_empty:
        return dict(merged)

    return {name: value for name, value in merged.items() if value}


def list_secret_entries() -> List[SecretEntry]:
    """Return metadata for all stored secrets."""
    overlay_path = _resolve_secrets_path()
    overlay = _read_raw(overlay_path, include_empty=True)

    base_path = _resolve_base_secrets_path()
    if base_path and base_path.exists() and base_path != overlay_path:
        base = _read_raw(base_path, include_empty=True)
    else:
        base = OrderedDict()

    names: List[str] = []
    seen: set[str] = set()

    for name in overlay.keys():
        names.append(name)
        seen.add(name)

    for name in base.keys():
        if name not in seen:
            names.append(name)
            seen.add(name)

    entries: List[SecretEntry] = []
    for name in names:
        if name in overlay:
            value = overlay.get(name)
            entries.append(SecretEntry(name=name, has_value=bool(value), is_overlay=True))
        else:
            value = base.get(name)
            entries.append(SecretEntry(name=name, has_value=bool(value), is_overlay=False))
    return entries


def get_secret_value(name: str) -> Optional[str]:
    """Return the stored value for a secret, if set."""
    if not name:
        return None

    overlay_path = _resolve_secrets_path()
    overlay = _read_raw(overlay_path)
    value = overlay.get(name)
    if value is None:
        base_path = _resolve_base_secrets_path()
        if base_path and base_path.exists():
            base = _read_raw(base_path)
            value = base.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def set_secret_value(name: str, value: Optional[str]) -> None:
    """Create or update a secret value."""
    if not name:
        raise ValueError("Secret name cannot be empty.")

    path = _resolve_secrets_path()
    secrets = _read_raw(path, include_empty=True)

    normalized = (value or "").strip()
    if not normalized:
        secrets[name] = None
    else:
        secrets[name] = normalized

    _write_raw(path, secrets)


def remove_secret(name: str) -> None:
    """Remove a secret from the store."""
    if not name:
        return
    path = _resolve_secrets_path()
    secrets = _read_raw(path, include_empty=True)
    if name in secrets:
        secrets[name] = None
        _write_raw(path, secrets)


def delete_secret(name: str) -> None:
    """Delete a secret entry entirely from the store."""
    if not name:
        return
    path = _resolve_secrets_path()
    secrets = _read_raw(path, include_empty=True)
    if name in secrets:
        del secrets[name]
        _write_raw(path, secrets)


def secret_has_value(name: str) -> bool:
    """Return True when the secret exists and has non-empty value."""
    return bool(get_secret_value(name))


def ensure_secrets_file() -> Path:
    """Create the secrets file if needed and return its path."""
    path = _resolve_secrets_path()
    _ensure_file(path)
    return path
