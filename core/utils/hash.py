"""Hash utilities shared across the codebase."""

from __future__ import annotations

import hashlib


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
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if length is None:
        return digest
    return digest[:length]
