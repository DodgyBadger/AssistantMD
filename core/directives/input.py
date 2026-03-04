"""
Input directive processor with directive-owned pattern resolution.
"""

import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from .base import DirectiveProcessor
from core.utils.patterns import PatternUtilities
from .parser import DirectiveValueParser
from core.utils.file_state import hash_file_content
from core.utils.frontmatter import parse_simple_frontmatter
from core.utils.routing import build_manifest, normalize_write_mode, parse_output_target, write_output
from core.runtime.buffers import get_buffer_store_for_scope
from core.logger import UnifiedLogger
from core.tools.utils import get_virtual_mount_key, resolve_virtual_path
from core.constants import SUPPORTED_READ_FILE_TYPES

logger = UnifiedLogger(tag="directive-input")


def load_file_with_metadata(file_path: str, vault_root: str) -> Dict[str, Any]:
    """Load content from a single file with metadata."""
    # Preserve explicit extension; default to .md only when no extension exists.
    normalized_path = file_path
    if "." not in os.path.basename(normalized_path):
        normalized_path = f"{normalized_path}.md"
    
    filename = os.path.splitext(os.path.basename(normalized_path))[0]
    extension = os.path.splitext(normalized_path)[1].lower()
    filepath_without_ext = (
        normalized_path[:-3] if normalized_path.endswith(".md") else normalized_path
    )

    kind = SUPPORTED_READ_FILE_TYPES.get(extension)
    if kind is None:
        return {
            "filepath": filepath_without_ext,
            "source_path": normalized_path,
            "filename": filename,
            "content": "",
            "found": False,
            "error": (
                f"Unsupported file type '{extension or '[none]'}'. "
                "Only markdown and image files are supported."
            ),
        }
    
    try:
        # Construct absolute path if needed
        is_virtual_mount = bool(get_virtual_mount_key(normalized_path))
        if is_virtual_mount:
            full_path, _mount = resolve_virtual_path(normalized_path)
        elif not os.path.isabs(file_path):
            full_path = os.path.join(vault_root, normalized_path)
        else:
            full_path = file_path

        # Resolve symlinks before enforcing vault boundaries.
        resolved_path = os.path.realpath(full_path)
        if not is_virtual_mount:
            vault_abs = os.path.realpath(vault_root)
            if not resolved_path.startswith(vault_abs + os.sep) and resolved_path != vault_abs:
                raise ValueError("Path escapes vault boundaries")

        if kind == "image":
            if not os.path.isfile(resolved_path):
                raise FileNotFoundError
            return {
                "filepath": filepath_without_ext,
                "source_path": normalized_path,
                "filename": filename,
                "content": "",
                "found": True,
                "error": None,
            }

        with open(resolved_path, "r", encoding="utf-8") as file:
            content = file.read()
        
        return {
            "filepath": filepath_without_ext,
            "source_path": normalized_path,
            "filename": filename,
            "content": content,
            "found": True,
            "error": None
        }
        
    except FileNotFoundError:
        return {
            "filepath": filepath_without_ext,
            "source_path": normalized_path,
            "filename": filename,
            "content": "",
            "found": False,
            "error": f"File not found: {filename}"
        }
    except Exception as e:
        if get_virtual_mount_key(normalized_path):
            return {
                "filepath": filepath_without_ext,
                "source_path": normalized_path,
                "filename": filename,
                "content": "",
                "found": False,
                "error": f"Error reading virtual mount file: {str(e)}"
            }
        return {
            "filepath": filepath_without_ext,
            "source_path": normalized_path,
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

    def _parse_input_target_and_parameters(self, value: str) -> tuple[str, Dict[str, str]]:
        allowed_parameters = {
            "required",
            "refs_only",
            "refs-only",
            "images",
            "head",
            "properties",
            "output",
            "write-mode",
            "write_mode",
            "scope",
        }
        base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
            value.strip(),
            allowed_parameters=allowed_parameters,
        )
        if self._has_unparsed_known_param_assignment(
            value=value,
            allowed_parameters=allowed_parameters,
            parsed_parameters={k.lower() for k in parameters.keys()},
        ):
            raise ValueError(
                "Malformed parameter block. If a value contains commas, wrap it in quotes "
                '(e.g. properties="name,description").'
            )

        return base_value, {k.lower(): v for k, v in parameters.items()}

    def _has_unparsed_known_param_assignment(
        self,
        *,
        value: str,
        allowed_parameters: set[str],
        parsed_parameters: set[str],
    ) -> bool:
        stripped = value.rstrip()
        if not stripped.endswith(")"):
            return False

        depth = 0
        open_idx: Optional[int] = None
        for idx in range(len(stripped) - 1, -1, -1):
            char = stripped[idx]
            if char == ")":
                depth += 1
            elif char == "(":
                depth -= 1
                if depth == 0:
                    open_idx = idx
                    break
        if open_idx is None or depth != 0:
            return False

        params_section = stripped[open_idx + 1 : -1]
        assignment_keys = {
            key.lower()
            for key in re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)\s*=", params_section)
        }
        known_assignment_keys = assignment_keys.intersection(allowed_parameters)
        return bool(known_assignment_keys - parsed_parameters)
    
    def validate_value(self, value: str) -> bool:
        if not value or not value.strip():
            return False

        # Parse base value and parameters
        try:
            base_value, parameters = self._parse_input_target_and_parameters(value.strip())
        except ValueError:
            return False

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

        # Validate parameters
        for param_name, param_value in parameters.items():
            param_name = param_name.lower()
            if param_name not in {
                'required',
                'refs_only',
                'refs-only',
                'images',
                'head',
                'properties',
                'output',
                'write-mode',
                'write_mode',
                'scope',
            }:
                return False
            if param_name in {'required', 'refs_only', 'refs-only'}:
                if param_value.lower() not in ['true', 'false', 'yes', 'no', '1', '0']:
                    return False
            if param_name == 'images':
                if param_value.lower() not in {'auto', 'ignore'}:
                    return False
            if param_name == 'head':
                try:
                    if int(param_value) <= 0:
                        return False
                except (TypeError, ValueError):
                    return False
            if param_name == 'properties':
                raw = (param_value or "").strip()
                if not raw:
                    continue
                lowered = raw.lower()
                if lowered in {'true', 'false', 'yes', 'no', '1', '0'}:
                    continue
                keys = [k.strip() for k in raw.split(",") if k.strip()]
                if not keys:
                    return False

        return True
    
    def process_value(self, value: str, vault_path: str, **context) -> List[Dict[str, Any]]:
        """Process input file with directive-specific pattern resolution.

        Supports optional 'required' parameter to signal workflow skip if no files found.
        Format: @input file: path/to/files (required) or @input file: path/to/files (required=true)
        """
        value = value.strip()

        # Parse optional parameters
        base_value, parameters = self._parse_input_target_and_parameters(value)
        required = parameters.get('required', '').lower() in ['true', 'yes', '1']
        refs_only = (
            parameters.get('refs_only', parameters.get('refs-only', '')).lower()
            in ['true', 'yes', '1']
        )
        images_policy = parameters.get("images", "auto").strip().lower() or "auto"
        head_chars = self._parse_head_chars(parameters.get('head'))
        properties_enabled, properties_keys = self._parse_properties_mode(parameters.get('properties'))
        output_target_value = parameters.get('output')
        write_mode_param = parameters.get('write-mode') or parameters.get('write_mode')
        scope_value = parameters.get('scope')

        if base_value.startswith("variable:"):
            variable_name = base_value[len("variable:"):].strip()
            buffer_store = get_buffer_store_for_scope(
                scope=scope_value,
                default_scope=context.get("buffer_scope", "run"),
                buffer_store=context.get("buffer_store"),
                buffer_store_registry=context.get("buffer_store_registry"),
            )
            display_name = f"variable: {variable_name}"
            if buffer_store is None:
                if required:
                    return [{
                        '_workflow_signal': 'skip_step',
                        'reason': f"Required input variable not available: {variable_name}",
                    }]
                return [{
                    "filepath": display_name,
                    "filename": variable_name,
                    "content": "",
                    "found": False,
                    "error": "Variable store unavailable",
                    "images_policy": images_policy,
                }]

            entry = buffer_store.get(variable_name)
            if entry is None:
                if required:
                    return [{
                        '_workflow_signal': 'skip_step',
                        'reason': f"Required input variable not found: {variable_name}",
                    }]
                return [{
                    "filepath": display_name,
                    "filename": variable_name,
                    "content": "",
                    "found": False,
                    "error": "Variable not found",
                    "images_policy": images_policy,
                }]

            content_value = entry.content or ""
            result = {
                "filepath": display_name,
                "filename": variable_name,
                "content": "" if refs_only else content_value,
                "found": True,
                "error": None,
                "images_policy": images_policy,
            }
            if refs_only:
                result["refs_only"] = True
            else:
                if properties_enabled:
                    result = self._apply_properties_mode(result, properties_keys)
                if head_chars is not None:
                    result = self._truncate_result_content(result, head_chars)
            results = [result]
            if output_target_value:
                return self._route_input_results(
                    results,
                    output_target_value,
                    write_mode_param,
                    vault_path,
                context,
                refs_only=refs_only,
                scope_value=scope_value,
            )
            return results

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
                    file_data['refs_only'] = True
                    file_data['content'] = ""
                    file_data["images_policy"] = images_policy
        else:
            if properties_enabled:
                result_files = [
                    self._apply_properties_mode(file_data, properties_keys)
                    if isinstance(file_data, dict) else file_data
                    for file_data in result_files
                ]
            if head_chars is not None:
                result_files = [
                    self._truncate_result_content(file_data, head_chars)
                    if isinstance(file_data, dict) else file_data
                    for file_data in result_files
                ]
            for file_data in result_files:
                if isinstance(file_data, dict):
                    file_data["images_policy"] = images_policy

        if output_target_value:
            return self._route_input_results(
                result_files,
                output_target_value,
                write_mode_param,
                vault_path,
                context,
                refs_only=refs_only,
                scope_value=scope_value,
            )

        return result_files

    def _parse_head_chars(self, head_value: Optional[str]) -> Optional[int]:
        if head_value is None or str(head_value).strip() == "":
            return None
        try:
            parsed = int(head_value)
        except (TypeError, ValueError):
            raise ValueError("head must be a positive integer") from None
        if parsed <= 0:
            raise ValueError("head must be a positive integer")
        return parsed

    def _parse_properties_mode(self, properties_value: Optional[str]) -> tuple[bool, Optional[List[str]]]:
        if properties_value is None:
            return False, None
        raw = str(properties_value).strip()
        if not raw:
            return True, None
        lowered = raw.lower()
        if lowered in {"true", "yes", "1"}:
            return True, None
        if lowered in {"false", "no", "0"}:
            return False, None
        keys = [key.strip() for key in raw.split(",") if key.strip()]
        if not keys:
            raise ValueError("properties must be true/false or a comma-separated key list")
        return True, keys

    def _apply_properties_mode(
        self,
        file_data: Dict[str, Any],
        requested_keys: Optional[List[str]],
    ) -> Dict[str, Any]:
        if not file_data.get("found", True):
            return file_data
        content = file_data.get("content")
        if not isinstance(content, str):
            return file_data

        try:
            props, _remaining = parse_simple_frontmatter(content, require_frontmatter=False)
        except ValueError:
            props = {}

        if requested_keys is None:
            selected = dict(props)
        else:
            selected = {key: props[key] for key in requested_keys if key in props}

        if not selected:
            file_data["refs_only"] = True
            file_data["content"] = ""
            file_data["properties_extracted"] = False
            file_data["properties_keys"] = requested_keys or []
            return file_data

        lines = [f"{key}: {self._format_property_value(value)}" for key, value in selected.items()]
        file_data["content"] = "\n".join(lines)
        file_data["properties_extracted"] = True
        file_data["properties_keys"] = list(selected.keys())
        return file_data

    def _format_property_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _truncate_result_content(self, file_data: Dict[str, Any], head_chars: int) -> Dict[str, Any]:
        if not file_data.get("found", True):
            return file_data
        if file_data.get("refs_only"):
            return file_data
        content = file_data.get("content")
        if not isinstance(content, str):
            return file_data
        original_chars = len(content)
        file_data["head"] = head_chars
        file_data["content_original_chars"] = original_chars
        if original_chars <= head_chars:
            file_data["content_truncated"] = False
            return file_data
        file_data["content"] = content[:head_chars]
        file_data["content_truncated"] = True
        return file_data

    def _route_input_results(
        self,
        result_files: List[Dict[str, Any]],
        output_target_value: str,
        write_mode_param: Optional[str],
        vault_path: str,
        context: Dict[str, Any],
        refs_only: bool,
        scope_value: Optional[str],
    ) -> List[Dict[str, Any]]:
        parsed_target = parse_output_target(
            output_target_value,
            vault_path,
            allow_context=bool(context.get("allow_context_output")),
            reference_date=context.get("reference_date"),
            week_start_day=context.get("week_start_day", 0),
        )
        if parsed_target.type == "inline":
            return result_files
        if parsed_target.type == "context":
            found_files = [
                file_data for file_data in result_files
                if isinstance(file_data, dict) and file_data.get("found", True)
            ]
            if refs_only:
                contents = [
                    file_data.get("filepath", "")
                    for file_data in found_files
                    if isinstance(file_data.get("filepath", ""), str)
                ]
                combined_content = "\n".join([c for c in contents if c])
            else:
                contents = [
                    file_data.get("content", "")
                    for file_data in found_files
                    if isinstance(file_data.get("content", ""), str)
                ]
                combined_content = "\n\n".join([c for c in contents if c])

            manifest = build_manifest(
                source="input",
                destination="context",
                item_count=len(found_files),
                total_chars=len(combined_content),
                paths=[
                    file_data.get("filepath")
                    for file_data in found_files
                    if file_data.get("filepath")
                ] or None,
            )
            routed_results: List[Dict[str, Any]] = []
            for file_data in result_files:
                if isinstance(file_data, dict):
                    file_data["refs_only"] = True
                    file_data["content"] = ""
                    file_data["routed_to"] = "context"
                routed_results.append(file_data)

            routed_results.append(
                {
                    "context_output": combined_content,
                    "manifest": manifest,
                    "found": True,
                }
            )
            return routed_results

        found_files = [
            file_data for file_data in result_files
            if isinstance(file_data, dict) and file_data.get("found", True)
        ]
        write_mode = normalize_write_mode(write_mode_param)
        if write_mode == "new" and len(found_files) > 1:
            routed_results: List[Dict[str, Any]] = []
            manifest_entries: List[Dict[str, Any]] = []
            routed_destinations: Dict[int, str] = {}

            for file_data in found_files:
                filepath = file_data.get("filepath") or file_data.get("filename") or "unknown"
                content_value = "" if refs_only else (file_data.get("content", "") or "")
                content_with_header = f"--- FILE: {filepath} ---\n{content_value}"
                write_result = write_output(
                    target=parsed_target,
                    content=content_with_header,
                    write_mode="new",
                    buffer_store=context.get("buffer_store"),
                    buffer_store_registry=context.get("buffer_store_registry"),
                    vault_path=vault_path,
                    buffer_scope=scope_value,
                    default_scope=context.get("buffer_scope", "run"),
                )

                destination = ""
                if write_result.get("type") == "buffer":
                    destination = f"variable: {write_result.get('name')}"
                elif write_result.get("type") == "file":
                    destination = f"file: {write_result.get('path')}"
                else:
                    destination = parsed_target.type

                routed_destinations[id(file_data)] = destination
                manifest_entries.append(
                    {
                        "manifest": build_manifest(
                            source="input",
                            destination=destination,
                            item_count=1,
                            total_chars=len(content_with_header),
                            paths=[filepath],
                    note="per-file routing (write-mode=new)",
                ),
                "found": True,
            }
                )

            logger.set_sinks(["validation"]).info(
                "input_routed",
                data={
                    "event": "input_routed",
                    "destination": f"{parsed_target.type} (per-file, write-mode=new)",
                    "refs_only": refs_only,
                    "item_count": len(found_files),
                    "total_chars": sum(
                        len(
                            f"--- FILE: {file_data.get('filepath') or file_data.get('filename') or 'unknown'} ---\n"
                            + ("" if refs_only else (file_data.get("content", "") or ""))
                        )
                        for file_data in found_files
                    ),
                },
            )

            for file_data in result_files:
                if isinstance(file_data, dict):
                    file_data["refs_only"] = True
                    file_data["content"] = ""
                    destination = routed_destinations.get(id(file_data))
                    if destination:
                        file_data["routed_to"] = destination
                routed_results.append(file_data)

            routed_results.extend(manifest_entries)
            return routed_results

        if refs_only:
            contents = [
                file_data.get("filepath", "")
                for file_data in found_files
                if isinstance(file_data.get("filepath", ""), str)
            ]
            combined_content = "\n".join([c for c in contents if c])
        else:
            contents = [
                file_data.get("content", "")
                for file_data in found_files
                if isinstance(file_data.get("content", ""), str)
            ]
            combined_content = "\n\n".join([c for c in contents if c])
        total_chars = len(combined_content)
        paths = [
            file_data.get("filepath")
            for file_data in found_files
            if file_data.get("filepath")
        ]

        write_result = write_output(
            target=parsed_target,
            content=combined_content,
            write_mode=write_mode,
            buffer_store=context.get("buffer_store"),
            buffer_store_registry=context.get("buffer_store_registry"),
            vault_path=vault_path,
            buffer_scope=scope_value,
            default_scope=context.get("buffer_scope", "run"),
        )

        destination = ""
        if write_result.get("type") == "buffer":
            destination = f"variable: {write_result.get('name')}"
        elif write_result.get("type") == "file":
            destination = f"file: {write_result.get('path')}"
        else:
            destination = parsed_target.type

        manifest = build_manifest(
            source="input",
            destination=destination,
            item_count=len(found_files),
            total_chars=total_chars,
            paths=paths or None,
        )

        logger.set_sinks(["validation"]).info(
            "input_routed",
            data={
                "event": "input_routed",
                "destination": destination,
                "refs_only": refs_only,
                "item_count": len(found_files),
                "total_chars": total_chars,
            },
        )

        routed_results: List[Dict[str, Any]] = []
        for file_data in result_files:
            if isinstance(file_data, dict):
                file_data['refs_only'] = True
                file_data['content'] = ""
                file_data['routed_to'] = destination
            routed_results.append(file_data)

        routed_results.append({"manifest": manifest, "found": True})
        return routed_results
    
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
        fmt = None
        if count is None:
            base_pattern, fmt = self.pattern_utils.parse_pattern_with_optional_format(pattern)
        
        # Extract directory path from parameter value
        pattern_start = value.find(f"{{{pattern}}}")
        pattern_end = pattern_start + len(pattern) + 2
        is_dir_mode = (
            base_pattern == 'latest'
            and fmt is None
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
        if base_pattern == 'pending' and fmt is None:
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
        elif count is not None or (base_pattern == 'latest' and fmt is None):
            # Multi-file patterns like {latest:3} (or {latest} -> {latest:1})
            resolved_count = count if count is not None else 1
            return self._resolve_time_based_multi_pattern(
                base_pattern,
                resolved_count,
                search_directory,
                vault_path,
                value,
                pattern,
                context.get('reference_date'),
                context.get('week_start_day', 0),
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
                                        original_value: str, pattern: str,
                                        reference_date: Optional[datetime],
                                        week_start_day: int) -> List[Dict[str, Any]]:
        """Handle time-based multi-file patterns like {latest:3}."""
        if count < 1:
            return []

        all_files = self.pattern_utils.get_directory_files(search_directory)
        
        if base_pattern == 'latest':
            matched_files = self.pattern_utils.get_latest_files(all_files, count)
        elif base_pattern == 'yesterday':
            now = reference_date or datetime.now()
            end_date = (now - timedelta(days=1)).date()
            start_date = (now - timedelta(days=count)).date()
            matched_files = self._select_files_in_date_range(
                all_files,
                start_date,
                end_date,
                limit=None,
            )
        elif base_pattern in {'this-week', 'last-week'}:
            now = reference_date or datetime.now()
            week_offset = 0 if base_pattern == 'this-week' else -1
            week_start = self.pattern_utils._get_week_start_date(now, week_start_day, week_offset).date()
            week_end = week_start + timedelta(days=6)
            matched_files = self._select_files_in_date_range(
                all_files,
                week_start,
                week_end,
                limit=count,
            )
        else:
            raise ValueError(
                f"Counted pattern '{{{base_pattern}:{count}}}' is not supported for @input"
            )
        
        # Load content from matched files
        result_files = []
        for file_path in matched_files:
            relative_path = os.path.relpath(file_path, vault_path)
            if relative_path.endswith('.md'):
                relative_path = relative_path[:-3]
            
            file_data = load_file_with_metadata(relative_path, vault_path)
            result_files.append(file_data)
        
        return result_files

    def _select_files_in_date_range(
        self,
        all_files: List[str],
        start_date,
        end_date,
        limit: Optional[int],
    ) -> List[str]:
        """Return files with date-bearing filenames in [start_date, end_date]."""
        dated_matches = []
        for filepath in all_files:
            file_date = self.pattern_utils.extract_date_from_filename(filepath)
            if not file_date:
                continue
            file_day = file_date.date()
            if start_date <= file_day <= end_date:
                dated_matches.append((file_date, filepath))

        # Most recent first for predictable recency-oriented selection.
        dated_matches.sort(key=lambda x: x[0], reverse=True)
        matched_files = [filepath for _, filepath in dated_matches]
        if limit is not None:
            matched_files = matched_files[:limit]
        return matched_files
    
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
