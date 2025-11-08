"""
Run-on directive processor.
"""

from typing import List
from .base import DirectiveProcessor
from .parser import DirectiveValueParser


class RunOnDirective(DirectiveProcessor):
    """Processor for @run-on directive that specifies days when a step should execute."""
    
    def get_directive_name(self) -> str:
        return "run-on"
    
    def validate_value(self, value: str) -> bool:
        """Validate run-on directive supports both comma and space separation."""
        if DirectiveValueParser.is_empty(value):
            return False
        
        valid_days = {
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
            'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
            'daily', 'never'
        }
        
        return DirectiveValueParser.validate_list_from_set(value, valid_days, to_lower=True)
    
    def process_value(self, value: str, vault_path: str, **context) -> List[str]:
        """Process run-on directive with standardized list parsing."""
        days = DirectiveValueParser.parse_list(value, to_lower=True)
        
        if not days:
            raise ValueError("No valid day names found")
        
        return days