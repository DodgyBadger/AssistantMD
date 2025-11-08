"""
Lightweight value objects shared across validation components.
"""

from dataclasses import dataclass


@dataclass
class APIResponse:
    """Wrapper for API response data."""

    status_code: int
    data: dict | None = None
    text: str = ""

    def json(self) -> dict:
        return self.data or {}


@dataclass
class CommandResult:
    """Result from CLI command execution."""

    return_code: int
    stdout: str = ""
    stderr: str = ""
