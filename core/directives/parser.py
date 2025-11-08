"""
Directive parser for extracting @directive-name value from step content.

This module provides functionality to parse directive lines from the beginning
of step content and return both the extracted directives and cleaned content.
Also provides centralized value parsing utilities for consistent behavior across
all directive processors.
"""

import re
from typing import Dict, List, Optional
from dataclasses import dataclass

from core.logger import UnifiedLogger

# Create module logger
logger = UnifiedLogger(tag="directive-parser")


#######################################################################
## Exception Classes
#######################################################################

class DirectiveParsingError(Exception):
    """Base exception for directive parsing errors."""
    pass


#######################################################################
## Data Classes
#######################################################################

@dataclass
class ParsedDirectives:
    """Result of parsing directives from step content."""
    directives: Dict[str, List[str]]
    cleaned_content: str
    
    def get_directive_values(self, directive_name: str) -> List[str]:
        """Get all values for a specific directive.
        
        Args:
            directive_name: Name of the directive
            
        Returns:
            List of values for the directive, empty list if not found
        """
        return self.directives.get(directive_name, [])
    
    def get_first_directive_value(self, directive_name: str) -> Optional[str]:
        """Get the first value for a directive.
        
        Args:
            directive_name: Name of the directive
            
        Returns:
            First value for the directive, None if not found or empty
        """
        values = self.get_directive_values(directive_name)
        return values[0] if values else None
    
    def has_directive(self, directive_name: str) -> bool:
        """Check if a directive exists.
        
        Args:
            directive_name: Name of the directive
            
        Returns:
            True if the directive exists, False otherwise
        """
        return directive_name in self.directives


#######################################################################
## Parsing Logic
#######################################################################

# Regex pattern for matching directive lines
# Matches: @directive-name value or @directive-name: value
# Groups: (directive-name, value)
DIRECTIVE_PATTERN = re.compile(r'^@([a-zA-Z][a-zA-Z0-9\-_]*):?\s+(.+)$')


@logger.trace("parse_directives")
def parse_directives(content: str) -> ParsedDirectives:
    """Parse directives from the beginning of step content.
    
    Extracts @directive-name value lines from the start of the content,
    stopping at the first non-directive, non-empty line. This allows
    directives to be mixed with empty lines but ensures they appear
    before any actual step content.
    
    Args:
        content: The step content to parse
        
    Returns:
        ParsedDirectives with extracted directives and cleaned content
        
    Examples:
        >>> content = '''@output-file planning/{today}
        ... @headers true
        ... 
        ... Create a weekly plan.'''
        >>> result = parse_directives(content)
        >>> result.directives
        {'output-file': ['planning/{today}'], 'headers': ['true']}
        >>> result.cleaned_content
        'Create a weekly plan.'
        
    Note:
        Multiple values for the same directive are supported and collected
        in a list. Empty lines between directives are ignored.
    """
    if not content:
        return ParsedDirectives(directives={}, cleaned_content="")
    
    lines = content.split('\n')
    directives: Dict[str, List[str]] = {}
    directive_section_end = 0
    
    # Parse directives from the beginning
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        
        # Skip empty lines in directive section
        if not stripped_line:
            continue
        
        # Try to match directive pattern
        match = DIRECTIVE_PATTERN.match(stripped_line)
        if match:
            directive_name = match.group(1)
            directive_value = match.group(2).strip()
            
            # Add to directives dictionary
            if directive_name not in directives:
                directives[directive_name] = []
            directives[directive_name].append(directive_value)
            
            # Mark this line as processed
            directive_section_end = i + 1
        else:
            # First non-directive line - stop parsing directives
            break
    
    # Extract cleaned content (everything after directive section)
    if directive_section_end < len(lines):
        # Find first non-empty line after directives
        content_start = directive_section_end
        for i in range(directive_section_end, len(lines)):
            if lines[i].strip():
                content_start = i
                break
        
        cleaned_lines = lines[content_start:]
        cleaned_content = '\n'.join(cleaned_lines)
    else:
        cleaned_content = ""
    
    return ParsedDirectives(
        directives=directives,
        cleaned_content=cleaned_content
    )


def is_valid_directive_line(line: str) -> bool:
    """Check if a line is a valid directive line.
    
    Args:
        line: Line to check
        
    Returns:
        True if the line matches directive pattern, False otherwise
    """
    stripped_line = line.strip()
    return bool(DIRECTIVE_PATTERN.match(stripped_line))


def extract_directive_from_line(line: str) -> Optional[tuple[str, str]]:
    """Extract directive name and value from a line.
    
    Args:
        line: Line to extract from
        
    Returns:
        Tuple of (directive_name, directive_value) if valid, None otherwise
        
    Examples:
        >>> extract_directive_from_line("@output-file planning/{today}")
        ('output-file', 'planning/{today}')
        >>> extract_directive_from_line("@input-file: goals.md")
        ('input-file', 'goals.md')
        >>> extract_directive_from_line("Not a directive")
        None
    """
    stripped_line = line.strip()
    match = DIRECTIVE_PATTERN.match(stripped_line)
    
    if match:
        directive_name = match.group(1)
        directive_value = match.group(2).strip()
        return (directive_name, directive_value)
    
    return None


#######################################################################
## Centralized Value Parsing Utilities
#######################################################################

class DirectiveValueParser:
    """Centralized parsing service for directive values.
    
    Provides consistent value parsing across all directive processors to eliminate
    parsing inconsistencies and enable reliable @tools directive implementation.
    """
    
    @staticmethod
    def is_empty(value: str) -> bool:
        """Check if value is empty or whitespace-only."""
        return not value or not value.strip()
    
    @staticmethod
    def normalize_string(value: str, to_lower: bool = True) -> str:
        """Normalize string value consistently."""
        normalized = value.strip()
        return normalized.lower() if to_lower else normalized
    
    @staticmethod
    def parse_list(value: str, to_lower: bool = True) -> List[str]:
        """
        Parse space/comma-separated values consistently.
        
        Supports both formats:
        - Comma-separated: "monday, tuesday, wednesday"
        - Space-separated: "monday tuesday wednesday" 
        - Mixed: "monday, tuesday wednesday"
        
        Args:
            value: The string to parse
            to_lower: Whether to normalize items to lowercase
            
        Returns:
            List of parsed, trimmed, non-empty items
        """
        if DirectiveValueParser.is_empty(value):
            return []
        
        # Split on both commas and whitespace, filter empty items
        items = [item.strip() for item in re.split(r'[,\s]+', value.strip()) if item.strip()]
        
        if to_lower:
            items = [item.lower() for item in items]
        
        return items
    
    @staticmethod
    def parse_boolean(value: str) -> bool:
        """
        Parse boolean values consistently.
        
        Treats these as True: 'true', 'yes', '1', 'on' (case-insensitive)
        Treats empty/missing value as True (for directives like @tools)
        Everything else as False
        
        Args:
            value: The string to parse
            
        Returns:
            Boolean value
        """
        if DirectiveValueParser.is_empty(value):
            # Empty value defaults to True for enabling directives
            return True
        
        normalized = value.strip().lower()
        return normalized in ['true', 'yes', '1', 'on']
    
    @staticmethod
    def validate_from_set(value: str, valid_values: set, to_lower: bool = True) -> bool:
        """
        Validate that a single value exists in a set of valid values.
        
        Args:
            value: The value to validate
            valid_values: Set of acceptable values
            to_lower: Whether to normalize for comparison
            
        Returns:
            True if value is in the valid set
        """
        if DirectiveValueParser.is_empty(value):
            return False
        
        normalized = DirectiveValueParser.normalize_string(value, to_lower)
        comparison_set = {v.lower() for v in valid_values} if to_lower else valid_values
        return normalized in comparison_set
    
    @staticmethod
    def validate_list_from_set(value: str, valid_values: set, to_lower: bool = True) -> bool:
        """
        Validate that all items in a list exist in a set of valid values.
        
        Args:
            value: The comma/space-separated string to validate
            valid_values: Set of acceptable values
            to_lower: Whether to normalize for comparison
            
        Returns:
            True if all parsed items are in the valid set
        """
        items = DirectiveValueParser.parse_list(value, to_lower)
        if not items:
            return False
        
        comparison_set = {v.lower() for v in valid_values} if to_lower else valid_values
        return all(item in comparison_set for item in items)
    
    @staticmethod
    def parse_value_with_parameters(value: str) -> tuple[str, Dict[str, str]]:
        """
        Parse a value that may contain parameters in parentheses.
        
        Supports formats like:
        - "sonnet" -> ("sonnet", {})
        - "sonnet (thinking)" -> ("sonnet", {"thinking": "true"})
        - "sonnet (thinking=true)" -> ("sonnet", {"thinking": "true"})
        - "sonnet (thinking=false, temperature=0.5)" -> ("sonnet", {"thinking": "false", "temperature": "0.5"})
        
        Args:
            value: The directive value to parse
            
        Returns:
            Tuple of (base_value, parameters_dict)
        """
        if DirectiveValueParser.is_empty(value):
            return "", {}
        
        value = value.strip()
        
        # Check if there are parameters in parentheses
        param_match = re.search(r'^([^(]+)\s*\(([^)]+)\)$', value)
        if not param_match:
            # No parameters found
            return value, {}
        
        base_value = param_match.group(1).strip()
        params_str = param_match.group(2).strip()
        
        # Parse parameters
        parameters = {}
        if params_str:
            # Split by commas and parse key=value or just key
            param_items = [item.strip() for item in params_str.split(',') if item.strip()]
            
            for param_item in param_items:
                if '=' in param_item:
                    # key=value format
                    key, val = param_item.split('=', 1)
                    parameters[key.strip()] = val.strip()
                else:
                    # Just key format (defaults to "true")
                    parameters[param_item.strip()] = "true"
        
        return base_value, parameters