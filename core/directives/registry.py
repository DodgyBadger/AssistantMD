"""
Parameter registry system for extensible directive processing.

This module provides the core registry functionality that manages directive processors
and enables extensible parameter processing without hardcoded parameter types.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from core.logger import UnifiedLogger
from .base import DirectiveProcessor

# Create module logger
logger = UnifiedLogger(tag="parameter-registry")


#######################################################################
## Exception Classes
#######################################################################

class ParameterRegistryError(Exception):
    """Base exception for parameter registry errors."""
    pass


class InvalidDirectiveError(ParameterRegistryError):
    """Raised when attempting to process an unregistered directive."""
    pass


class DuplicateDirectiveError(ParameterRegistryError):
    """Raised when attempting to register a directive that already exists."""
    pass


#######################################################################
## Data Classes
#######################################################################

@dataclass
class DirectiveProcessingResult:
    """Result of processing a directive value."""
    directive_name: str
    processed_value: Any
    success: bool
    error_message: Optional[str] = None


#######################################################################
## Registry Implementation
#######################################################################

class ParameterRegistry:
    """Registry for directive processors.
    
    Manages registration, lookup, and processing of directive types.
    Provides extensibility without requiring changes to core processing logic.
    """
    
    def __init__(self):
        """Initialize an empty parameter registry."""
        self._processors: Dict[str, DirectiveProcessor] = {}
    
    @logger.trace("register_directive")
    def register_directive(self, processor: DirectiveProcessor) -> None:
        """Register a directive processor.
        
        Args:
            processor: The directive processor to register
            
        Raises:
            DuplicateDirectiveError: If a processor for this directive is already registered
        """
        directive_name = processor.get_directive_name()
        
        if directive_name in self._processors:
            raise DuplicateDirectiveError(
                f"Directive '{directive_name}' is already registered"
            )
        
        self._processors[directive_name] = processor
    
    def is_directive_registered(self, directive_name: str) -> bool:
        """Check if a directive is registered.
        
        Args:
            directive_name: Name of the directive to check
            
        Returns:
            True if the directive is registered, False otherwise
        """
        return directive_name in self._processors
    
    def get_processor(self, directive_name: str) -> DirectiveProcessor:
        """Get the processor for a directive.
        
        Args:
            directive_name: Name of the directive
            
        Returns:
            The directive processor
            
        Raises:
            InvalidDirectiveError: If the directive is not registered
        """
        if directive_name not in self._processors:
            raise InvalidDirectiveError(
                f"Unknown directive: '{directive_name}'. "
                f"Registered directives: {list(self._processors.keys())}"
            )
        
        return self._processors[directive_name]
    
    def get_registered_directives(self) -> List[str]:
        """Get a list of all registered directive names.
        
        Returns:
            List of directive names
        """
        return list(self._processors.keys())
    
    @logger.trace("process_directive")
    def process_directive(self, directive_name: str, value: str, vault_path: str, **context) -> DirectiveProcessingResult:
        """Process a directive value using its registered processor.
        
        This is the main entry point for directive processing. It validates the
        directive value and processes it through the appropriate processor.
        
        Args:
            directive_name: Name of the directive
            value: The directive value to process
            vault_path: Path to the vault for context-aware processing
            **context: Additional context for processing (reference_date, week_start_day, etc.)
            
        Returns:
            Processing result with success/failure information and processed value
            
        Raises:
            InvalidDirectiveError: If the directive is not registered
            ValueError: If the value is invalid or cannot be processed
        """
        processor = self.get_processor(directive_name)
        
        # Validate the value first
        if not processor.validate_value(value):
            raise ValueError(
                f"Invalid value for directive '{directive_name}': '{value}'"
            )
        
        try:
            processed_value = processor.process_value(value, vault_path, **context)
            return DirectiveProcessingResult(
                directive_name=directive_name,
                processed_value=processed_value,
                success=True
            )
        except Exception as e:
            return DirectiveProcessingResult(
                directive_name=directive_name,
                processed_value=None,
                success=False,
                error_message=str(e)
            )
    
    def get_directive_documentation(self, directive_name: str) -> Dict[str, str]:
        """Get documentation for a directive.
        
        Args:
            directive_name: Name of the directive
            
        Returns:
            Dictionary with basic documentation information
            
        Raises:
            InvalidDirectiveError: If the directive is not registered
        """
        processor = self.get_processor(directive_name)
        
        return {
            "name": directive_name,
            "processor": processor.__class__.__name__
        }
    
    def get_all_documentation(self) -> Dict[str, Dict[str, str]]:
        """Get documentation for all registered directives.
        
        Returns:
            Dictionary mapping directive names to their basic documentation
        """
        docs = {}
        for directive_name in self._processors.keys():
            docs[directive_name] = self.get_directive_documentation(directive_name)
        return docs


#######################################################################
## Global Registry Instance
#######################################################################

# Global registry instance that will be used throughout the application
_global_registry = ParameterRegistry()


def get_global_registry() -> ParameterRegistry:
    """Get the global parameter registry instance.
    
    This is the main entry point for accessing the registry throughout
    the application. The global registry is initialized when this module
    is imported and pre-populated with built-in directives.
    
    Returns:
        The global registry instance
    """
    return _global_registry


def register_directive(processor: DirectiveProcessor) -> None:
    """Register a directive processor with the global registry.
    
    Convenience function for registering with the global registry.
    
    Args:
        processor: The directive processor to register
    """
    _global_registry.register_directive(processor)