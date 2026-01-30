"""
Input directive processor with directive-owned pattern resolution.
"""

import os
import re
from typing import List, Dict, Any, Optional

from .base import DirectiveProcessor
from .pattern_utilities import PatternUtilities
from .parser import DirectiveValueParser
from core.directives.file_state import hash_file_content


def load_file_with_metadata(file_path: str, vault_root: str) -> Dict[str, Any]:
    """Load content from a single file with metadata."""
    # Normalize file path for metadata
    normalized_path = file_path
    if not normalized_path.endswith('.md'):
        normalized_path = f"{normalized_path}.md"
    
    # Extract filename without extension for metadata
    filename = os.path.basename(file_path).replace('.md', '')
    filepath_without_ext = file_path.replace('.md', '') if file_path.endswith('.md') else file_path
    
    try:
        # Construct absolute path if needed
        if not os.path.isabs(file_path):
            full_path = os.path.join(vault_root, normalized_path)
        else:
            full_path = file_path
        
        with open(full_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        return {
            "filepath": filepath_without_ext,
            "filename": filename,
            "content": content,
            "found": True,
            "error": None
        }
        
    except FileNotFoundError:
        return {
            "filepath": filepath_without_ext,
            "filename": filename,
            "content": "",
            "found": False,
            "error": f"File not found: {filename}"
        }
    except Exception as e:
        return {
            "filepath": filepath_without_ext,
            "filename": filename,
            "content": "",
            "found": False,
            "error": f"Error reading file: {str(e)}"
        }


class InputFileDirective(DirectiveProcessor):
    """
    Input directive with directive-owned pattern resolution.
    
    Loads file content from specified paths with support for time-based, glob, and stateful patterns.
    
    Supported Patterns:
        # Time-based patterns
        {today}           - Files with today's date in filename
        {yesterday}       - Files with yesterday's date in filename  
        {tomorrow}        - Files with tomorrow's date in filename
        {this-week}       - Files from current week
        {last-week}       - Files from previous week
        {next-week}       - Files from next week  
        {this-month}      - Files from current month
        {last-month}      - Files from previous month
        {latest}          - Most recent file by date
        {latest:N}        - N most recent files by date
        {yesterday:N}     - Files from last N days
        {this-week:N}     - Up to N files from current week
        {last-week:N}     - Up to N files from previous week
        
        # Stateful patterns (require state management)
        {pending}         - Unprocessed files (oldest first, default limit 10)
        {pending:N}       - Up to N oldest unprocessed files
        
        # Glob patterns (single directory only, no recursion)
        *.md              - All .md files in vault root
        folder/*.md       - All .md files in specific folder
        prefix*.md        - All .md files starting with prefix
        *-draft.md        - All .md files ending with -draft
    
    Examples:
        @input file:goals.md                    # Direct file reference
        @input file:journal/{today}             # Today's journal entry
        @input file:journal/{latest:3}          # 3 most recent journal files
        @input file:notes/{pending:5}           # 5 oldest unprocessed notes
        @input file:projects/{this-week}        # All files from current week
        @input file:*.md                        # All markdown files in root
        @input file:journal/*.md                # All journal files
        @input file:draft-*.md                  # All files starting with "draft-"
        
    Security Notes:
        - Glob patterns restricted to single directories only
        - No recursive patterns (**/) allowed
        - No parent directory access (../) allowed
        - Multiple @input directives required for multiple directories
    """
    
    def __init__(self):
        self.pattern_utils = PatternUtilities()
    
    def get_directive_name(self) -> str:
        return "input"
    
    def validate_value(self, value: str) -> bool:
        if not value or not value.strip():
            return False

        # Parse base value and parameters
        base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
            value.strip(),
            allowed_parameters={"required", "refs_only", "refs-only"},
        )

        if not base_value:
            return False

        if base_value.startswith("file:"):
            file_path = base_value[len("file:"):].strip()
            if not file_path:
                return False
            if file_path.startswith('/') or '..' in file_path:
                return False
        elif base_value.startswith("variable:"):
            variable_name = base_value[len("variable:"):].strip()
            if not variable_name:
                return False
        else:
            return False

        # Validate parameters (currently 'required' and 'refs_only' are supported)
        for param_name, param_value in parameters.items():
            param_name = param_name.lower()
            if param_name not in {'required', 'refs_only', 'refs-only'}:
                return False
            # Validate required parameter is a boolean-like value
            if param_value.lower() not in ['true', 'false', 'yes', 'no', '1', '0']:
                return False

        return True
    
    def process_value(self, value: str, vault_path: str, **context) -> List[Dict[str, Any]]:
        """Process input file with directive-specific pattern resolution.

        Supports optional 'required' parameter to signal workflow skip if no files found.
        Format: @input file:path/to/files (required) or @input file:path/to/files (required=true)
        """
        value = value.strip()

        # Parse required parameter if present
        base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
            value, allowed_parameters={"required", "refs_only", "refs-only"}
        )
        required = parameters.get('required', '').lower() in ['true', 'yes', '1']
        refs_only = (
            parameters.get('refs_only', parameters.get('refs-only', '')).lower()
            in ['true', 'yes', '1']
        )

        if base_value.startswith("variable:"):
            variable_name = base_value[len("variable:"):].strip()
            buffer_store = context.get("buffer_store")
            if buffer_store is None:
                if required:
                    return [{
                        '_workflow_signal': 'skip_step',
                        'reason': f"Required input variable not available: {variable_name}",
                    }]
                return [{
                    "filepath": f"variable:{variable_name}",
                    "filename": variable_name,
                    "content": "",
                    "found": False,
                    "error": "Variable store unavailable",
                }]

            entry = buffer_store.get(variable_name)
            if entry is None:
                if required:
                    return [{
                        '_workflow_signal': 'skip_step',
                        'reason': f"Required input variable not found: {variable_name}",
                    }]
                return [{
                    "filepath": f"variable:{variable_name}",
                    "filename": variable_name,
                    "content": "",
                    "found": False,
                    "error": "Variable not found",
                }]

            content_value = entry.content or ""
            result = {
                "filepath": f"variable:{variable_name}",
                "filename": variable_name,
                "content": "" if refs_only else content_value,
                "found": True,
                "error": None,
            }
            if refs_only:
                result["paths_only"] = True
            return [result]

        if base_value.startswith("file:"):
            file_path = base_value[len("file:"):].strip()
        else:
            raise ValueError("Input target must start with file: or variable:")

        # Strip Obsidian-style square brackets for hotlinked files
        if file_path.startswith('[[') and file_path.endswith(']]'):
            file_path = file_path[2:-2]

        # Check for different pattern types and resolve files
        if '{' in file_path:
            # Time-based or stateful pattern ({latest:3}, {pending:5})
            result_files = self._resolve_brace_pattern(file_path, vault_path, **context)
        elif '*' in file_path:
            # Glob pattern (*.md, folder/*.md, prefix*.md)
            result_files = self._resolve_glob_pattern(file_path, vault_path)
        else:
            # Direct file reference
            result_files = [load_file_with_metadata(file_path, vault_path)]

        # If required=true and no files found, return skip signal
        # Check both: empty list OR all files have found=False
        if required:
            if len(result_files) == 0:
                return [{
                    '_workflow_signal': 'skip_step',
                    'reason': f'No required input files found: {file_path}'
                }]
            # Check if all files have found=False
            if all(not file_data.get('found', True) for file_data in result_files):
                return [{
                    '_workflow_signal': 'skip_step',
                    'reason': f'No required input files found: {file_path}'
                }]

        # If refs_only=true, strip content to reduce prompt size but retain metadata
        if refs_only:
            for file_data in result_files:
                if isinstance(file_data, dict):
                    file_data['paths_only'] = True
                    file_data['content'] = ""

        return result_files
    
    def _resolve_glob_pattern(self, glob_pattern: str, vault_path: str) -> List[Dict[str, Any]]:
        """Handle glob patterns - single directory only, no recursion."""
        
        # Security validation - reject dangerous patterns
        if '**' in glob_pattern or '..' in glob_pattern:
            raise ValueError(f"Recursive or parent directory glob patterns not allowed: {glob_pattern}")
        
        # Use pattern utilities for safe glob resolution
        matched_files = self.pattern_utils.resolve_safe_glob(glob_pattern, vault_path)
        
        # Load content from all matched files
        result_files = []
        for file_path in matched_files:
            relative_path = os.path.relpath(file_path, vault_path)
            if relative_path.endswith('.md'):
                relative_path = relative_path[:-3]
            
            file_data = load_file_with_metadata(relative_path, vault_path)
            result_files.append(file_data)
        
        return result_files
    
    def _resolve_brace_pattern(self, value: str, vault_path: str, **context) -> List[Dict[str, Any]]:
        """Handle brace patterns like {latest:3}, {pending:5}, {today}."""
        brace_patterns = re.findall(r'\{([^}]+)\}', value)
        
        if len(brace_patterns) != 1:
            raise ValueError(f"Multiple time patterns not supported: {value}")
        
        pattern = brace_patterns[0]
        base_pattern, count = self.pattern_utils.parse_pattern_with_count(pattern)
        
        # Extract directory path from parameter value
        pattern_start = value.find(f"{{{pattern}}}")
        pattern_end = pattern_start + len(pattern) + 2
        is_dir_mode = (
            base_pattern == 'latest'
            and pattern_end < len(value)
            and value[pattern_end] == '/'
        )
        if pattern_start > 0:
            # Path prefix exists (e.g., "journal/{latest:3}")
            path_prefix = value[:pattern_start]
            search_directory = os.path.join(vault_path, path_prefix)
        else:
            # No path prefix (e.g., "{latest:3}")
            search_directory = vault_path
        
        # Handle {pending} pattern with state management
        if base_pattern == 'pending':
            return self._resolve_pending_pattern(value, search_directory, vault_path, count, context.get('state_manager'))
        
        # Handle time-based patterns
        elif base_pattern == 'latest' and is_dir_mode:
            return self._resolve_latest_directory_pattern(
                value,
                vault_path,
                path_prefix if pattern_start > 0 else "",
                pattern_end,
                count,
            )
        elif count is not None or base_pattern == 'latest':
            # Multi-file patterns like {latest:3} (or {latest} -> {latest:1})
            resolved_count = count if count is not None else 1
            return self._resolve_time_based_multi_pattern(
                base_pattern,
                resolved_count,
                search_directory,
                vault_path,
                value,
                pattern,
            )
        else:
            # Single file patterns like {today}
            return self._resolve_single_time_pattern(value, vault_path, **context)

    def _resolve_latest_directory_pattern(
        self,
        original_value: str,
        vault_path: str,
        path_prefix: str,
        pattern_end: int,
        count: Optional[int],
    ) -> List[Dict[str, Any]]:
        """Resolve {latest} when used as a directory segment (e.g., logs/{latest}/file.md)."""
        if count not in (None, 1):
            raise ValueError("'{latest:N}' not supported for directory resolution in @input")

        search_directory = os.path.join(vault_path, path_prefix)
        latest_dir = self._find_latest_dated_subdir(search_directory)
        if not latest_dir:
            return []

        # Suffix after the required trailing slash
        suffix = original_value[pattern_end + 1:]
        resolved_prefix = os.path.join(path_prefix, latest_dir)
        if not suffix:
            # Default to glob all files in the latest directory
            resolved_path = os.path.join(resolved_prefix, "*")
        else:
            resolved_path = os.path.join(resolved_prefix, suffix)

        if "*" in resolved_path:
            return self._resolve_glob_pattern(resolved_path, vault_path)

        return [load_file_with_metadata(resolved_path, vault_path)]

    def _find_latest_dated_subdir(self, directory: str) -> Optional[str]:
        """Return the latest subdirectory name based on a date in the name."""
        if not os.path.exists(directory):
            return None

        dated_dirs = []
        for name in os.listdir(directory):
            full_path = os.path.join(directory, name)
            if not os.path.isdir(full_path):
                continue
            dir_date = self.pattern_utils.extract_date_from_filename(name)
            if dir_date:
                dated_dirs.append((dir_date, name))

        if not dated_dirs:
            return None

        dated_dirs.sort(key=lambda x: x[0], reverse=True)
        return dated_dirs[0][1]
    
    def _resolve_pending_pattern(self, original_value: str, search_dir: str,
                               vault_path: str, count: Optional[int],
                               state_manager) -> List[Dict[str, Any]]:
        """Handle {pending} pattern - InputFileDirective-specific logic."""
        all_files = self.pattern_utils.get_directory_files(search_dir)

        if state_manager:
            pending_files = state_manager.get_pending_files(all_files, original_value, count or 10)
        else:
            pending_files = all_files[:count] if count else all_files[:10]

        # Load file content and mark for state tracking
        result_files = []
        for file_path in pending_files:
            relative_path = os.path.relpath(file_path, vault_path)
            if relative_path.endswith('.md'):
                relative_path = relative_path[:-3]

            file_data = load_file_with_metadata(relative_path, vault_path)
            result_files.append(file_data)

        # Mark first file with state metadata if we have files
        # Store both content hash (for comparison) and filepath (for debugging)
        if result_files:
            file_records = []
            for f in result_files:
                if f['found'] and f['content']:
                    file_records.append({
                        'content_hash': hash_file_content(f['content']),
                        'filepath': f['filepath']  # Store for debugging
                    })

            result_files[0]['_state_metadata'] = {
                'requires_tracking': True,
                'pattern': original_value,
                'file_records': file_records
            }

        return result_files
    
    def _resolve_time_based_multi_pattern(self, base_pattern: str, count: int, 
                                        search_directory: str, vault_path: str,
                                        original_value: str, pattern: str) -> List[Dict[str, Any]]:
        """Handle time-based multi-file patterns like {latest:3}."""
        all_files = self.pattern_utils.get_directory_files(search_directory)
        
        if base_pattern == 'latest':
            matched_files = self.pattern_utils.get_latest_files(all_files, count)
        else:
            # For other patterns, use simple approach for now
            matched_files = all_files[:count]
        
        # Load content from matched files
        result_files = []
        for file_path in matched_files:
            relative_path = os.path.relpath(file_path, vault_path)
            if relative_path.endswith('.md'):
                relative_path = relative_path[:-3]
            
            file_data = load_file_with_metadata(relative_path, vault_path)
            result_files.append(file_data)
        
        return result_files
    
    def _resolve_single_time_pattern(self, value: str, vault_path: str, **context) -> List[Dict[str, Any]]:
        """Handle single time patterns like {today}."""
        reference_date = context.get('reference_date')
        week_start_day = context.get('week_start_day', 0)
        
        # Find the pattern in braces
        brace_patterns = re.findall(r'\{([^}]+)\}', value)
        if not brace_patterns:
            return [load_file_with_metadata(value, vault_path)]
        
        # Resolve the pattern to a date string
        pattern = brace_patterns[0]
        resolved_date = self.pattern_utils.resolve_date_pattern(pattern, reference_date, week_start_day)
        resolved_path = value.replace(f'{{{pattern}}}', resolved_date)

        if '*' in resolved_path:
            return self._resolve_glob_pattern(resolved_path, vault_path)

        return [load_file_with_metadata(resolved_path, vault_path)]
