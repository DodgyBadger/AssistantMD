"""
Base class for all tool implementations.

Provides a standard interface for tool creation and instruction generation.
"""

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic_ai.tools import Tool


class ToolRecoveryPolicy(StrEnum):
    """Developer-declared recovery semantics for an interrupted tool call."""

    UNKNOWN = "unknown"
    REPLAY_SAFE = "replay_safe"
    VAULT_TRANSACTIONAL = "vault_transactional"
    MANUAL_REQUIRED = "manual_required"


class BaseTool(ABC):
    """Base class for all tools in the system."""

    @classmethod
    @abstractmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Get the Pydantic AI Tool implementation.

        Args:
            vault_path: Optional path to vault for tools that need vault context
        """
        pass

    @classmethod
    def get_recovery_policy(cls) -> ToolRecoveryPolicy:
        """Return interruption recovery semantics, failing closed by default."""
        return ToolRecoveryPolicy.UNKNOWN
