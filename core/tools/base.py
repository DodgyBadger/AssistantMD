"""
Base class for all tool implementations.

Provides a standard interface for tool creation and instruction generation.
"""

from abc import ABC, abstractmethod
from pydantic_ai.tools import Tool


class BaseTool(ABC):
    """Base class for all tools in the system."""
    
    @classmethod
    @abstractmethod
    def get_tool(cls, vault_path: str = None) -> Tool:
        """Get the Pydantic AI Tool implementation.
        
        Args:
            vault_path: Optional path to vault for tools that need vault context
        """
        pass
    
    @classmethod
    @abstractmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for this tool."""
        pass
