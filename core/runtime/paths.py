"""
Runtime-aware path helpers.

Provides centralized access to data, system, and docs roots, preferring the
runtime context when available and falling back to container defaults.
"""

import os
from pathlib import Path

from core.runtime.state import get_runtime_context, has_runtime_context

# Default roots (env-driven). Kept here to discourage direct import elsewhere.
_DEFAULT_DATA_ROOT = "/app/data"
_DEFAULT_SYSTEM_ROOT = "/app/system"
_DEFAULT_DOCS_ROOT = os.getenv("DOCS_ROOT", "/app/docs")


def get_data_root() -> Path:
    """Return the active data root (vaults)."""
    if has_runtime_context():
        try:
            return Path(get_runtime_context().config.data_root)
        except Exception:
            pass
    return Path(os.getenv("CONTAINER_DATA_ROOT", _DEFAULT_DATA_ROOT))


def get_system_root() -> Path:
    """Return the active system root (settings, secrets, logs, DBs)."""
    if has_runtime_context():
        try:
            return Path(get_runtime_context().config.system_root)
        except Exception:
            pass
    return Path(os.getenv("CONTAINER_SYSTEM_ROOT", _DEFAULT_SYSTEM_ROOT))


def get_docs_root() -> Path:
    """Return the docs root."""
    return Path(_DEFAULT_DOCS_ROOT)
