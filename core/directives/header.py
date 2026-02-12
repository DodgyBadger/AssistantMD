"""
Header directive processor for controlling step output headers.
"""

import re
from datetime import datetime

from .base import DirectiveProcessor
from core.utils.patterns import PatternUtilities


class HeaderDirective(DirectiveProcessor):
    """
    Header directive processor for customizing step output headers.
    
    Allows specification of headers using literal text and pattern variables.
    Supports the same time-based patterns as output directive for consistency.
    
    Supported Patterns:
        {today}           - Current date (YYYY-MM-DD)
        {yesterday}       - Previous day date
        {tomorrow}        - Next day date
        {this-week}       - Current week start date
        {last-week}       - Previous week start date  
        {next-week}       - Next week start date
        {this-month}      - Current month (YYYY-MM)
        {last-month}      - Previous month (YYYY-MM)
        {day-name}        - Current day name (e.g., Monday)
        {month-name}      - Current month name (e.g., January)
        
    Examples:
        @header Daily Planning - {today}        # Daily Planning - 2025-08-07
        @header Weekly Review ({this-week})     # Weekly Review (2025-08-04)
        @header Goals for {this-month}          # Goals for 2025-08
        @header {day-name} Planning              # Monday Planning
        @header {month-name} Review              # January Review
        @header Sprint Planning                 # Sprint Planning (literal)
    """
    
    def __init__(self):
        self.pattern_utils = PatternUtilities()
    
    def get_directive_name(self) -> str:
        return "header"
    
    def validate_value(self, value: str) -> bool:
        """Validate header value - any non-empty string is valid."""
        return bool(value and value.strip())
    
    def process_value(self, value: str, vault_path: str, **context) -> str:
        """Process header value with pattern resolution."""
        value = value.strip()
        
        # Extract context parameters with defaults
        reference_date = context.get('reference_date', datetime.now())
        week_start_day = context.get('week_start_day', 0)
        
        # Find all brace patterns in the header
        brace_patterns = re.findall(r'\{([^}]+)\}', value)
        
        if not brace_patterns:
            # No patterns - return as-is
            return value
        
        # Resolve each pattern and substitute back
        resolved_header = value
        for pattern in brace_patterns:
            base_pattern, count = self.pattern_utils.parse_pattern_with_count(pattern)
            if count is None:
                base_pattern, _fmt = self.pattern_utils.parse_pattern_with_optional_format(pattern)
            
            # Validate pattern is appropriate for headers
            if base_pattern == 'pending':
                raise ValueError("'{pending}' pattern not supported in @header directive")
            elif count is not None:
                raise ValueError(f"Multi-file pattern '{pattern}' not supported in @header directive")
            
            # Resolve the pattern to a string
            resolved_value = self._resolve_header_pattern(pattern, reference_date, week_start_day)
            resolved_header = resolved_header.replace(f'{{{pattern}}}', resolved_value)
        
        return resolved_header
    
    def _resolve_header_pattern(self, pattern: str, reference_date: datetime, week_start_day: int) -> str:
        """Resolve patterns specific to header directive needs."""

        base_pattern, _fmt = self.pattern_utils.parse_pattern_with_optional_format(pattern)

        if base_pattern in ['today', 'yesterday', 'tomorrow', 'this-week', 'last-week',
                           'next-week', 'this-month', 'last-month', 'day-name', 'month-name']:
            return self.pattern_utils.resolve_date_pattern(pattern, reference_date, week_start_day)
        
        else:
            # Unknown pattern, return as-is (could be a literal)
            return pattern
