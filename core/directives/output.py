"""
Output directive processor with directive-owned pattern resolution.
"""

import os
import re
from datetime import datetime

from .base import DirectiveProcessor
from core.utils.patterns import PatternUtilities
from .parser import DirectiveValueParser


class OutputFileDirective(DirectiveProcessor):
    """
    Output directive with directive-owned pattern resolution.
    
    Generates single file paths from patterns. Supports time-based patterns for 
    creating organized file structures.
    
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
        @output file:planning/{today}           # planning/2025-08-07
        @output file:journal/{this-week}        # journal/2025-08-04  
        @output file:reports/monthly/{this-month}  # reports/monthly/2025-08
        @output file:tasks/{day-name}           # tasks/Thursday
        @output file:monthly/{month-name}       # monthly/September
        @output file:goals                      # goals (literal path)
    
    Note: {pending} and multi-file patterns like {latest:3} are not supported
    for output targets as they don't make sense in this context.

    Special Targets:
        context          - Emit output into the chat agent context (context manager only)
    """
    
    def __init__(self):
        self.pattern_utils = PatternUtilities()
    
    def get_directive_name(self) -> str:
        return "output"
    
    def validate_value(self, value: str) -> bool:
        if not value or not value.strip():
            return False

        base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
            value.strip(),
            allowed_parameters={"scope"},
        )

        if parameters and "scope" not in parameters:
            return False

        if not base_value:
            return False

        if base_value == "context":
            if parameters:
                return False
        elif base_value.startswith("file:"):
            file_path = base_value[len("file:"):].strip()
            if not file_path:
                return False
            if file_path.startswith('/') or '..' in file_path:
                return False
            if parameters.get("scope"):
                return False
        elif base_value.startswith("variable:"):
            variable_name = base_value[len("variable:"):].strip()
            if not variable_name:
                return False
        else:
            return False

        return True
    
    def process_value(self, value: str, vault_path: str, **context) -> str:
        """Process output file with directive-specific pattern resolution."""
        value = value.strip()

        base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
            value,
            allowed_parameters={"scope"},
        )
        if parameters and "scope" not in parameters:
            raise ValueError("Output target does not accept parameters")

        if base_value == "context":
            if parameters:
                raise ValueError("Context output does not accept parameters")
            return {"type": "context"}

        if base_value.startswith("variable:"):
            variable_name = base_value[len("variable:"):].strip()
            if not variable_name:
                raise ValueError("Variable name is required for variable output")
            scope_value = parameters.get("scope")
            return {"type": "buffer", "name": variable_name, "scope": scope_value}

        if base_value.startswith("file:"):
            if parameters.get("scope"):
                raise ValueError("Scope is only supported for variable outputs")
            value = base_value[len("file:"):].strip()
        else:
            raise ValueError("Output target must start with file: or variable:")
        
        # Strip Obsidian-style square brackets for hotlinked files
        if value.startswith('[[') and value.endswith(']]'):
            value = value[2:-2]
        
        # Extract context parameters with defaults
        reference_date = context.get('reference_date', datetime.now())
        week_start_day = context.get('week_start_day', 0)
        
        # Check for brace patterns
        brace_patterns = re.findall(r'\{([^}]+)\}', value)
        
        if not brace_patterns:
            # No patterns - normalize extension and return
            return self._normalize_markdown_extension(value)
        
        # Resolve each pattern and substitute back
        resolved_path = value
        for pattern in brace_patterns:
            base_pattern, count = self.pattern_utils.parse_pattern_with_count(pattern)
            
            # Validate pattern is appropriate for output files
            if base_pattern == 'pending':
                raise ValueError("'{pending}' pattern not supported in @output directive")
            elif count is not None:
                raise ValueError(f"Multi-file pattern '{pattern}' not supported in @output directive")
            
            # Resolve the pattern to a date string
            resolved_value = self._resolve_output_pattern(base_pattern, reference_date, week_start_day, vault_path)
            resolved_path = resolved_path.replace(f'{{{pattern}}}', resolved_value)
        
        # Normalize extension after pattern resolution
        return self._normalize_markdown_extension(resolved_path)
    
    def _resolve_output_pattern(self, pattern: str, reference_date: datetime, 
                              week_start_day: int, vault_path: str) -> str:
        """Resolve patterns specific to output directive needs (single paths)."""
        
        if pattern in ['today', 'yesterday', 'tomorrow', 'this-week', 'last-week', 
                      'next-week', 'this-month', 'last-month']:
            return self.pattern_utils.resolve_date_pattern(pattern, reference_date, week_start_day)
        
        elif pattern == 'latest':
            # For output files, {latest} means "most recent file date" or today
            return self._find_latest_file_date(vault_path, reference_date)
        
        else:
            # Unknown pattern, return as-is (could be a literal)
            return pattern
    
    def _find_latest_file_date(self, vault_path: str, reference_date: datetime) -> str:
        """Find the date of the most recent file or return today's date."""
        try:
            all_files = self.pattern_utils.get_directory_files(vault_path)
            if all_files:
                latest_files = self.pattern_utils.get_latest_files(all_files, 1)
                if latest_files:
                    # Extract date from the latest file
                    file_date = self.pattern_utils.extract_date_from_filename(latest_files[0])
                    if file_date:
                        return file_date.strftime('%Y-%m-%d')
        except Exception:
            pass
        
        # Fallback to today if no files found or error occurred
        return reference_date.strftime('%Y-%m-%d')
    
    def _normalize_markdown_extension(self, file_path: str) -> str:
        """
        Normalize file path to ensure proper .md extension.
        
        This enforces the system constraint that all output files must be markdown.
        - If already ends with .md, return as-is
        - If ends with other extension, strip it and add .md  
        - If no extension, add .md
        
        Args:
            file_path: The file path to normalize
            
        Returns:
            Normalized file path ending with .md
        """
        if file_path.endswith('.md'):
            return file_path
        
        # Check if there's an extension to strip
        base_name = os.path.basename(file_path)
        if '.' in base_name:
            # Remove extension from the last part of the path
            path_parts = file_path.rsplit('.', 1)
            return f"{path_parts[0]}.md"
        else:
            # No extension, just add .md
            return f"{file_path}.md"
