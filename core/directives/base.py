"""
Base classes for directive processing system.

This module provides the core DirectiveProcessor abstract base class
moved from parameter_registry.py for better organization.
"""

from abc import ABC, abstractmethod
from typing import Any


class DirectiveProcessor(ABC):
    """Base class for directive processors.
    
    Each directive type (output-file, input-file, headers, etc.) implements
    this interface to provide validation and processing logic.
    """
    
    @abstractmethod
    def get_directive_name(self) -> str:
        """Return the name of the directive this processor handles.
        
        Returns:
            The directive name (e.g., "output-file", "headers", "input-file")
        """
        pass
    
    @abstractmethod
    def validate_value(self, value: str) -> bool:
        """Validate a directive value.
        
        Args:
            value: The directive value to validate
            
        Returns:
            True if the value is valid, False otherwise
        """
        pass
    
    @abstractmethod
    def process_value(self, value: str, vault_path: str, **context) -> Any:
        """Process a directive value and return the processed result.
        
        Args:
            value: The directive value to process
            vault_path: Path to the vault for context-aware processing
            **context: Additional context for processing (reference_date, week_start_day, etc.)
            
        Returns:
            The processed value (type depends on directive)
            
        Raises:
            ValueError: If the value cannot be processed
        """
        pass