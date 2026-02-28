"""Hash utilities shared across the codebase."""

from __future__ import annotations

import hashlib
from pathlib import Path


def _truncate_digest(digest: str, length: int | None) -> str:
    if length is None:
        return digest
    return digest[:length]


def hash_bytes(content: bytes, length: int | None = 16) -> str:
    """Create a SHA256 hash for binary content."""
    digest = hashlib.sha256(content).hexdigest()
    return _truncate_digest(digest, length)


def hash_file_bytes(path: str | Path, length: int | None = 16) -> str:
    """Create a SHA256 hash for a file's raw bytes via streaming read."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return _truncate_digest(digest.hexdigest(), length)


def hash_file_content(content: str, length: int | None = 16) -> str:
    """Create a hash of file content for unique identification.

    Uses SHA256 hash of file content. This approach:
    - Is path-independent (files can be moved/renamed)
    - Detects content changes (will re-process if file is edited)
    - Avoids path format issues (relative vs absolute, with/without extensions)

    Args:
        content: File content to hash.
        length: Optional output length. Use None for full hash.

    Returns:
        SHA256 hash (optionally truncated).
    """
    return hash_bytes(content.encode("utf-8"), length=length)
