"""
Base class for all tool implementations.

Provides a standard interface for tool creation and instruction generation.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic_ai.tools import Tool


class ToolRecoveryPolicy(StrEnum):
    """Developer-declared recovery semantics for an interrupted tool call."""

    UNKNOWN = "unknown"
    REPLAY_SAFE = "replay_safe"
    VAULT_TRANSACTIONAL = "vault_transactional"
    MANUAL_REQUIRED = "manual_required"


ASSISTANTMD_TOOL_METADATA_KEY = "assistantmd"
TOOL_RECOVERY_POLICY_METADATA_KEY = "recovery_policy"


def tool_recovery_metadata(policy: ToolRecoveryPolicy) -> dict[str, str]:
    """Build the stable AssistantMD metadata carried by a bound tool."""
    return {TOOL_RECOVERY_POLICY_METADATA_KEY: policy.value}


def recovery_policy_from_tool_metadata(metadata: Any) -> ToolRecoveryPolicy:
    """Decode bound-tool recovery metadata, failing closed when malformed."""
    if not isinstance(metadata, Mapping):
        return ToolRecoveryPolicy.UNKNOWN
    assistantmd = metadata.get(ASSISTANTMD_TOOL_METADATA_KEY)
    if not isinstance(assistantmd, Mapping):
        return ToolRecoveryPolicy.UNKNOWN
    raw_policy = assistantmd.get(TOOL_RECOVERY_POLICY_METADATA_KEY)
    if not isinstance(raw_policy, str):
        return ToolRecoveryPolicy.UNKNOWN
    try:
        return ToolRecoveryPolicy(raw_policy)
    except ValueError:
        return ToolRecoveryPolicy.UNKNOWN


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
