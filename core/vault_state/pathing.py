"""Vault-relative path resolution for mutation recording."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_vault_relative_path(
    *,
    vault_path: str | Path,
    path: str,
    markdown_only: bool = False,
) -> Path:
    """Resolve a vault-relative path while enforcing vault boundaries."""
    if ".." in path:
        raise ValueError("Path traversal not allowed - '..' found in path")
    if path.startswith("/"):
        raise ValueError("Absolute paths not allowed")
    if markdown_only and "." in os.path.basename(path) and not path.endswith(".md"):
        raise ValueError("Only .md files are allowed. Please use '.md' extension for all files.")

    vault_root = Path(vault_path).resolve()
    candidate = (vault_root / path).resolve()
    try:
        candidate.relative_to(vault_root)
    except ValueError as exc:
        raise ValueError("Path escapes vault boundaries") from exc
    return candidate


def normalize_vault_relative_path(path: str | Path) -> str:
    """Normalize a vault-relative path for database storage."""
    return str(path).replace("\\", "/").strip().strip("/")
