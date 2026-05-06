"""Vault-state excluded path pattern matching."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExcludedPathMatcher:
    """Small gitignore-style matcher for normalized vault-relative paths."""

    patterns: tuple[str, ...]

    @classmethod
    def from_patterns(cls, patterns: list[str] | tuple[str, ...]) -> "ExcludedPathMatcher":
        return cls(patterns=tuple(_normalize_pattern(pattern) for pattern in patterns if pattern))

    def matches(self, relative_path: str | Path) -> bool:
        """Return True when a path should be excluded."""
        normalized = _normalize_path(relative_path)
        for pattern in self.patterns:
            if not pattern:
                continue
            if pattern.endswith("/"):
                prefix = pattern.rstrip("/")
                if normalized == prefix or normalized.startswith(f"{prefix}/"):
                    return True
                continue
            if fnmatch.fnmatchcase(normalized, pattern):
                return True
            if "/" not in pattern and fnmatch.fnmatchcase(Path(normalized).name, pattern):
                return True
        return False


def _normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip().strip("/")


def _normalize_pattern(pattern: str) -> str:
    return str(pattern).replace("\\", "/").strip().lstrip("/")
