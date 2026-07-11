"""Vault-relative path resolution for mutation recording."""

from __future__ import annotations

import os
from pathlib import Path


class VaultRootResolutionError(ValueError):
    """Raised when a configured vault root cannot be resolved safely."""

    def __init__(self, code: str, message: str, *, vault_name: str):
        super().__init__(message)
        self.code = code
        self.vault_name = vault_name


def resolve_configured_vault_root(*, data_root: str | Path, vault_name: str) -> Path:
    """Resolve one first-level vault directory without escaping the data root."""
    normalized_name = str(vault_name or "").strip()
    name_path = Path(normalized_name)
    if (
        not normalized_name
        or normalized_name in {".", ".."}
        or name_path.name != normalized_name
        or "/" in normalized_name
        or "\\" in normalized_name
    ):
        raise VaultRootResolutionError(
            "invalid_vault_name",
            f"Invalid vault name: {vault_name}",
            vault_name=normalized_name,
        )

    resolved_data_root = Path(data_root).resolve()
    candidate = (resolved_data_root / normalized_name).resolve()
    try:
        candidate.relative_to(resolved_data_root)
    except ValueError as exc:
        raise VaultRootResolutionError(
            "vault_root_escapes_data_root",
            f"Vault root escapes the configured data root: {normalized_name}",
            vault_name=normalized_name,
        ) from exc
    if not candidate.is_dir():
        raise VaultRootResolutionError(
            "vault_not_found",
            f"Vault not found: {normalized_name}",
            vault_name=normalized_name,
        )
    return candidate


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
