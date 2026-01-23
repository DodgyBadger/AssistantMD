"""
Workflow configuration parser and step processor.

This module provides utilities for:
1. Parsing workflow definition files (markdown) with YAML frontmatter
2. Step processing orchestration for directive-based workflow execution
"""

import re
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from core.constants import VALID_WEEK_DAYS
from core.scheduling.parser import parse_schedule_syntax, ScheduleParsingError
from core.directives.parser import parse_directives
from core.directives.bootstrap import ensure_builtin_directives_registered
from core.directives.registry import get_global_registry, InvalidDirectiveError


# Create module logger
from core.logger import UnifiedLogger
logger = UnifiedLogger(tag="workflow-parser")


#######################################################################
## Pydantic Configuration Schema
#######################################################################

class WorkflowConfigSchema(BaseModel):
    """Pydantic schema for workflow definition configuration validation.
    
    Provides automatic validation, type conversion, and default values
    for workflow metadata loaded from YAML frontmatter.
    """
    # Required fields
    workflow_engine: str = Field(..., description="Workflow engine module to execute")
    
    # Optional fields with defaults
    schedule: Optional[str] = Field(None, description="Schedule string for when the workflow runs, None for manual-only")
    enabled: bool = Field(True, description="Whether the workflow is enabled (only relevant if scheduled)")
    week_start_day: str = Field("monday", description="Week start day for weekly patterns")
    description: str = Field("", description="Human-readable description")
    
    @field_validator('schedule')
    @classmethod
    def validate_schedule(cls, v: Optional[str]) -> Optional[str]:
        """Validate schedule syntax using the schedule parser."""
        if v is None:
            return None  # Allow None for manual-only workflows
        try:
            # Parse to validate syntax - we don't use the result, just check it's valid
            parse_schedule_syntax(v)
            return v.strip()
        except ScheduleParsingError as e:
            raise ValueError(f"Invalid schedule syntax: {str(e)}")
    
    @field_validator('week_start_day')
    @classmethod
    def validate_week_start_day(cls, v: str) -> str:
        """Validate and normalize week start day to lowercase."""
        v_lower = v.lower().strip()
        if v_lower not in VALID_WEEK_DAYS:
            raise ValueError(f"week_start_day must be one of: {', '.join(VALID_WEEK_DAYS)}, got: {v}")
        return v_lower
    
    class Config:
        extra = "ignore"  # Ignore unknown fields (allows custom Obsidian properties)
        str_strip_whitespace = True  # Auto-strip strings


#######################################################################
## YAML Frontmatter Parsing Functions
#######################################################################

def parse_frontmatter(content: str) -> Tuple[dict, str]:
    """Extract frontmatter key-value pairs and remaining content.

    Parses frontmatter as simple key: value pairs without YAML interpretation.
    This avoids YAML syntax restrictions and allows any characters in values.

    Args:
        content: Full file content starting with frontmatter

    Returns:
        Tuple of (config_dict, remaining_content)

    Raises:
        ValueError: If frontmatter format is invalid
    """
    content = content.strip()

    if not content.startswith('---'):
        raise ValueError("Workflow file must start with YAML frontmatter (---)")

    lines = content.split('\n')
    if len(lines) < 3:
        raise ValueError("Invalid frontmatter format: file too short")

    # Find closing ---
    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("Frontmatter not properly closed with ---")

    # Parse key-value pairs (split on first colon only)
    config = {}
    for line_num, line in enumerate(lines[1:end_idx], 2):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue

        # Must contain colon
        if ':' not in line:
            raise ValueError(f"Line {line_num}: Invalid format, expected 'key: value'")

        # Split on first colon only - everything after is the value
        key, value = line.split(':', 1)
        key = key.strip()
        value = value.strip()

        if not key:
            raise ValueError(f"Line {line_num}: Empty key not allowed")

        # Strip matching quotes (Obsidian adds these automatically)
        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'"):
                value = value[1:-1]

        # Convert common boolean strings
        if value.lower() in ('true', 'yes', 'on'):
            config[key] = True
        elif value.lower() in ('false', 'no', 'off'):
            config[key] = False
        else:
            # Keep as string (Pydantic will handle type conversion)
            config[key] = value

    # Extract remaining content
    remaining_content = '\n'.join(lines[end_idx + 1:])

    return config, remaining_content


#######################################################################
## Markdown Parsing Utilities
#######################################################################

def parse_markdown_sections(content: str, delimiter: str = "##") -> Dict[str, str]:
    """Extract markdown sections from content using specified delimiter.
    
    Args:
        content: Full file content
        delimiter: Section delimiter (default "##" for ## HEADING)
        
    Returns:
        Dictionary mapping section names to content
        
    Examples:
        sections = parse_markdown_sections(content)  # Uses ## HEADING
        sections = parse_markdown_sections(content, "#")  # Uses # HEADING
        sections = parse_markdown_sections(content, "###")  # Uses ### HEADING
    """
    sections = {}
    
    # Escape delimiter for regex and build pattern
    escaped_delimiter = re.escape(delimiter)
    section_pattern = rf'^{escaped_delimiter} (.+?)\s*\n(.*?)(?=^{escaped_delimiter} |\Z)'
    
    matches = re.findall(section_pattern, content, re.MULTILINE | re.DOTALL)
    
    for section_name, section_content in matches:
        sections[section_name] = section_content.strip()
    
    return sections


def parse_workflow_file(file_path: str, context_id: str = None) -> Dict[str, str]:
    """Parse workflow definition file with YAML frontmatter format.
    
    Reads workflow file with frontmatter configuration and markdown sections.
    Returns sections dictionary with frontmatter config stored in special key.
    
    Args:
        file_path: Path to the workflow markdown file
        context_id: Optional context ID for logging (e.g., global_id)
        
    Returns:
        Dictionary mapping section names to content, plus '__FRONTMATTER_CONFIG__' key
        
    Raises:
        FileNotFoundError: If the workflow file doesn't exist
        ValueError: If file cannot be parsed or frontmatter is invalid
    """
    try:
        # Read workflow file content
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Extract frontmatter configuration and remaining content
        frontmatter_config, remaining_content = parse_frontmatter(content)
        
        # Parse remaining content into sections
        sections = parse_markdown_sections(remaining_content, "##")
        
        # Store frontmatter config in special key for workflow loader
        sections['__FRONTMATTER_CONFIG__'] = frontmatter_config
        
        return sections
        
    except FileNotFoundError:
        error_msg = f"Workflow file not found: {file_path}"
        raise FileNotFoundError(error_msg)
    except Exception as e:
        error_msg = f"Failed to parse workflow file {file_path}: {str(e)}"
        raise ValueError(error_msg) from e


def get_workflow_sections(sections: Dict[str, str]) -> Dict[str, str]:
    """
    Returns all sections except reserved sections and internal keys.
    All remaining sections are treated as workflow steps in file order.
    
    Args:
        sections: Parsed sections dictionary from parse_workflow_file()
        
    Returns:
        Dictionary with all sections except reserved sections
    """
    reserved_sections = {'__FRONTMATTER_CONFIG__'}
    return {k: v for k, v in sections.items() if k not in reserved_sections}


def validate_config(config: dict, vault: str, name: str) -> dict:
    """Validate workflow configuration from template or user file using Pydantic.
    
    Uses the WorkflowConfigSchema for validation with automatic type conversion,
    defaults, and comprehensive validation rules.
    
    Args:
        config: Configuration dictionary from YAML frontmatter
        vault: Vault name for error context
        name: Workflow name for error context
        
    Returns:
        Validated configuration dictionary with normalized values and defaults
        
    Raises:
        ValueError: If validation fails or required fields are missing
    """
    try:
        # Use Pydantic schema for validation
        validated_config = WorkflowConfigSchema(**config)
        
        # Convert back to dictionary format expected by callers
        return validated_config.model_dump()
        
    except Exception as e:
        # Handle Pydantic validation errors and other exceptions
        error_msg = f"Failed to validate configuration for {vault}/{name}: {str(e)}"
        
        # Add user-facing vault log for configuration errors
        logger.error(
            "Invalid workflow configuration detected",
            data={
                "vault": f"{vault}/{name}",
                "config_error": str(e),
                "fix_suggestion": "Check YAML frontmatter syntax and required fields",
            },
        )
        
        raise ValueError(error_msg) from e


#######################################################################
## Step Processing Data Classes
#######################################################################

@dataclass
class ProcessedStep:
    """Result of processing a workflow step with directives.
    
    Contains clean content and processed directive results. Individual workflows
    decide how to use these results (e.g., how to handle input files, output paths, etc.).
    """
    content: str                        # Clean step content (directives removed)
    directive_config: Dict[str, Any]    # Processed directive results
    
    def get_directive_value(self, directive_name: str, default=None):
        """Get the processed value for a specific directive.
        
        Args:
            directive_name: Name of the directive (with hyphens converted to underscores)
            default: Default value if directive not found
            
        Returns:
            The processed directive value, or default if not found
            
        Examples:
            result.get_directive_value('output_file')  # for @output-file
            result.get_directive_value('input_file', [])  # for @input-file
        """
        return self.directive_config.get(directive_name, default)


#######################################################################
## Step Processing Functions
#######################################################################

@logger.trace("process_step_content")
def process_step_content(
    step_content: str, 
    vault_path: str, 
    reference_date: Optional[datetime] = None,
    week_start_day: int = 0,
    state_manager=None
) -> ProcessedStep:
    """Process workflow step content by extracting and processing directives.
    
    This is the main entry point for directive processing. It coordinates:
    1. Directive parsing (extracting @directive-name value from step headers)
    2. Directive processing (resolving time patterns, loading files, etc.)
    3. Content processing (extensible content pipeline, currently pass-through)
    
    The results are workflow-agnostic - individual workflows decide how to use
    the processed directive results and clean content.
    
    Args:
        step_content: Raw step content with directives and prompt text
        vault_path: Path to the vault for file resolution and context
        reference_date: Reference date for time pattern resolution (defaults to now)
        week_start_day: Week start day for week-based patterns (0=Monday, 6=Sunday)
        state_manager: Optional state manager for stateful patterns like {pending}
        
    Returns:
        ProcessedStep with clean content and processed directive configuration
        
    Raises:
        ValueError: If directive processing fails or invalid patterns are encountered
    """
    ensure_builtin_directives_registered()

    if reference_date is None:
        reference_date = datetime.now()
       
    try:
        # Parse directives from step content
        parsed = parse_directives(step_content)
        
        # Process each directive through the registry
        registry = get_global_registry()
        directive_config = {}
        
        for directive_name, values in parsed.directives.items():
            try:
                # Process each value for this directive
                processed_values = []
                for value in values:
                    result = registry.process_directive(
                        directive_name, 
                        value, 
                        vault_path, 
                        reference_date=reference_date,
                        week_start_day=week_start_day,
                        state_manager=state_manager
                    )
                    if not result.success:
                        raise ValueError(f"Failed to process directive '{directive_name}': {result.error_message}")
                    processed_values.append(result.processed_value)
                
                # Store results in config (normalize directive name to use underscores)
                config_key = directive_name.replace('-', '_')
                if len(processed_values) == 1:
                    directive_config[config_key] = processed_values[0]
                else:
                    directive_config[config_key] = processed_values
                
            except InvalidDirectiveError as e:
                # Unknown directive - provide helpful error message
                available_directives = registry.get_registered_directives()
                raise ValueError(f"Unknown directive '{directive_name}'. Available directives: {', '.join(available_directives)}") from e
            
            except Exception as e:
                # Other processing errors
                raise ValueError(f"Failed to process directive '{directive_name}': {str(e)}") from e
        
        
        processed_content = parsed.cleaned_content.strip()
        
        return ProcessedStep(
            content=processed_content,
            directive_config=directive_config
        )
        
    except Exception as e:
        error_msg = f"Failed to process step content: {str(e)}"
        raise ValueError(error_msg) from e
