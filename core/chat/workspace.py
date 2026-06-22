"""Workspace path helpers for chat sessions and surfaces."""

from __future__ import annotations

from pathlib import PurePosixPath


def normalize_workspace_path(path: str | None) -> str:
    """Normalize a safe vault-relative workspace path string."""
    raw_path = (path or "").strip().replace("\\", "/")
    if not raw_path:
        return ""
    if raw_path.startswith("/"):
        raise ValueError("Workspace path must be relative to the vault.")
    parts = [part for part in raw_path.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("Workspace path cannot contain '..'.")
    return PurePosixPath(*parts).as_posix() if parts else ""
