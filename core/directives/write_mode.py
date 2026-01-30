"""
Write-mode directive processor.

Handles @write-mode directive for controlling how content is written to output files.
Supports 'append' (default) and 'new' modes for different file creation behaviors.
"""

from .base import DirectiveProcessor
from .parser import DirectiveValueParser


class WriteModeDirective(DirectiveProcessor):
    """Processor for @write-mode directive that controls file writing behavior."""
    
    VALID_MODES = {'append', 'new', 'replace'}
    
    def get_directive_name(self) -> str:
        return "write-mode"
    
    def validate_value(self, value: str) -> bool:
        """Validate that the write mode value is recognized."""
        return DirectiveValueParser.validate_from_set(value, self.VALID_MODES, to_lower=True)
    
    def process_value(self, value: str, vault_path: str, **context) -> str:
        """Process write mode value and return the normalized mode.
        
        Args:
            value: Write mode value (e.g., 'append', 'new')
            vault_path: Path to vault (not used for write-mode directive)
            **context: Additional context (not used for write-mode directive)
            
        Returns:
            Normalized write mode ('append', 'new', or 'replace')
            
        Raises:
            ValueError: If write mode is not recognized
        """
        if DirectiveValueParser.is_empty(value):
            raise ValueError("Write mode cannot be empty")
        
        mode = DirectiveValueParser.normalize_string(value, to_lower=True)
        
        if mode not in self.VALID_MODES:
            valid_modes = ', '.join(sorted(self.VALID_MODES))
            raise ValueError(f"Invalid write mode '{value}'. Valid modes are: {valid_modes}")
        
        return mode
