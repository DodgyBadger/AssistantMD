"""Shared typed input resolution for workflow authoring surfaces."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.constants import SUPPORTED_READ_FILE_TYPES
from core.logger import UnifiedLogger
from core.runtime.buffers import get_buffer_store_for_scope
from core.tools.utils import get_virtual_mount_key, resolve_virtual_path
from core.utils.frontmatter import parse_simple_frontmatter
from core.utils.hash import hash_file_bytes, hash_file_content
from core.utils.patterns import PatternUtilities
from core.utils.routing import (
    build_manifest,
    write_output,
)
from core.authoring.shared.output_resolution import (
    normalize_write_mode,
    parse_output_value,
    resolve_output_request,
)

logger = UnifiedLogger(tag="workflow-input-resolution")

INPUT_BOOLEAN_PARAMS = {"required", "refs_only", "refs-only", "pending", "latest"}
INPUT_ALLOWED_PARAMETERS = {
    "required",
    "refs_only",
    "refs-only",
    "images",
    "head",
    "tail",
    "properties",
    "output",
    "write-mode",
    "write_mode",
    "scope",
    "pending",
    "latest",
    "limit",
    "order",
    "dir",
    "dt_pattern",
    "dt_format",
}


@dataclass(frozen=True)
class InputSelectorOptions:
    mode: str | None
    limit: int | None
    order: str
    dir: str
    dt_pattern: str | None
    dt_format: str | None


@dataclass(frozen=True)
class InputResolutionRequest:
    target_type: str
    target: str
    required: bool = False
    refs_only: bool = False
    images_policy: str = "auto"
    head_chars: int | None = None
    tail_chars: int | None = None
    properties_enabled: bool = False
    properties_keys: list[str] | None = None
    output_target_value: str | None = None
    write_mode_param: str | None = None
    scope_value: str | None = None
    selector: InputSelectorOptions | None = None


def load_file_with_metadata(file_path: str, vault_root: str) -> dict[str, Any]:
    """Load content from a single file with metadata."""
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
        is_virtual_mount = bool(get_virtual_mount_key(normalized_path))
        if is_virtual_mount:
            full_path, _mount = resolve_virtual_path(normalized_path)
        elif not os.path.isabs(file_path):
            full_path = os.path.join(vault_root, normalized_path)
        else:
            full_path = file_path

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
            "error": None,
        }
    except FileNotFoundError:
        return {
            "filepath": filepath_without_ext,
            "source_path": normalized_path,
            "filename": filename,
            "content": "",
            "found": False,
            "error": f"File not found: {filename}",
        }
    except Exception as exc:
        logger.exception(
            "Failed to load file metadata",
            metadata={"file_path": normalized_path, "vault_root": vault_root},
        )
        if get_virtual_mount_key(normalized_path):
            return {
                "filepath": filepath_without_ext,
                "source_path": normalized_path,
                "filename": filename,
                "content": "",
                "found": False,
                "error": f"Error reading virtual mount file: {str(exc)}",
            }
        return {
            "filepath": filepath_without_ext,
            "source_path": normalized_path,
            "filename": filename,
            "content": "",
            "found": False,
            "error": f"Error reading file: {str(exc)}",
        }


def build_input_request(*, target_type: str, target: str, parameters: dict[str, Any]) -> InputResolutionRequest:
    normalized_params = {str(k).lower(): v for k, v in parameters.items()}
    _validate_parameter_combinations(target_type=target_type, parameters=normalized_params)
    required = _is_truthy_param(normalized_params, "required")
    refs_only = _is_truthy_param(normalized_params, "refs_only") or _is_truthy_param(
        normalized_params, "refs-only"
    )
    images_policy = str(normalized_params.get("images", "auto")).strip().lower() or "auto"
    head_chars, tail_chars = _parse_truncation_parameters(normalized_params)
    properties_enabled, properties_keys = _parse_properties_mode(normalized_params.get("properties"))
    selector = _parse_selector_options(normalized_params)
    output_target_value = _clean_optional_string(normalized_params.get("output"))
    write_mode_param = _clean_optional_string(
        normalized_params.get("write-mode") or normalized_params.get("write_mode")
    )
    scope_value = _clean_optional_string(normalized_params.get("scope"))
    return InputResolutionRequest(
        target_type=target_type,
        target=target,
        required=required,
        refs_only=refs_only,
        images_policy=images_policy,
        head_chars=head_chars,
        tail_chars=tail_chars,
        properties_enabled=properties_enabled,
        properties_keys=properties_keys,
        output_target_value=output_target_value,
        write_mode_param=write_mode_param,
        scope_value=scope_value,
        selector=selector,
    )


def resolve_input_request(
    request: InputResolutionRequest,
    *,
    vault_path: str,
    reference_date: datetime | None = None,
    week_start_day: int = 0,
    state_manager=None,
    buffer_store=None,
    buffer_store_registry: dict[str, Any] | None = None,
    buffer_scope: str = "run",
    allow_context_output: bool = False,
) -> list[dict[str, Any]]:
    resolver = WorkflowInputResolver()
    return resolver.resolve(
        request,
        vault_path=vault_path,
        reference_date=reference_date,
        week_start_day=week_start_day,
        state_manager=state_manager,
        buffer_store=buffer_store,
        buffer_store_registry=buffer_store_registry,
        buffer_scope=buffer_scope,
        allow_context_output=allow_context_output,
    )


class WorkflowInputResolver:
    """Shared runtime resolver for workflow inputs."""

    def __init__(self) -> None:
        self.pattern_utils = PatternUtilities()

    def resolve(self, request: InputResolutionRequest, *, vault_path: str, **context) -> list[dict[str, Any]]:
        if request.target_type == "variable":
            results = self._resolve_variable_target(request=request, context=context)
            if results and results[0].get("_workflow_signal") == "skip_step":
                return results
            if request.output_target_value:
                return self._route_input_results(
                    results,
                    request.output_target_value,
                    request.write_mode_param,
                    vault_path,
                    context,
                    refs_only=request.refs_only,
                    scope_value=request.scope_value,
                )
            return results

        if request.target_type != "file":
            raise ValueError("Input target must be file or variable")

        file_path = request.target.strip()
        if file_path.startswith("[[") and file_path.endswith("]]"):
            file_path = file_path[2:-2]

        if "{" in file_path:
            result_files = self._resolve_brace_pattern(file_path, vault_path, **context)
        elif "*" in file_path:
            result_files = self._resolve_glob_pattern(file_path, vault_path)
        else:
            result_files = [load_file_with_metadata(file_path, vault_path)]

        result_files = self._apply_selector_mode(
            result_files=result_files,
            input_expression=file_path,
            vault_path=vault_path,
            selector_options=request.selector,
            state_manager=context.get("state_manager"),
        )

        if request.required:
            if len(result_files) == 0 or all(not f.get("found", True) for f in result_files):
                return [self._skip_step_result(f"No required input files found: {file_path}")]

        if request.refs_only:
            for file_data in result_files:
                if isinstance(file_data, dict):
                    file_data["refs_only"] = True
                    file_data["content"] = ""
                    file_data["images_policy"] = request.images_policy
        else:
            if request.properties_enabled:
                result_files = [
                    self._apply_properties_mode(file_data, request.properties_keys)
                    if isinstance(file_data, dict)
                    else file_data
                    for file_data in result_files
                ]
            if request.head_chars is not None or request.tail_chars is not None:
                result_files = [
                    self._truncate_result_content(
                        file_data,
                        head_chars=request.head_chars,
                        tail_chars=request.tail_chars,
                    )
                    if isinstance(file_data, dict)
                    else file_data
                    for file_data in result_files
                ]
            for file_data in result_files:
                if isinstance(file_data, dict):
                    file_data["images_policy"] = request.images_policy

        if request.output_target_value:
            return self._route_input_results(
                result_files,
                request.output_target_value,
                request.write_mode_param,
                vault_path,
                context,
                refs_only=request.refs_only,
                scope_value=request.scope_value,
            )
        return result_files

    def _skip_step_result(self, reason: str) -> dict[str, Any]:
        return {"_workflow_signal": "skip_step", "reason": reason}

    def _resolve_variable_target(self, *, request: InputResolutionRequest, context: dict[str, Any]) -> list[dict[str, Any]]:
        buffer_store = get_buffer_store_for_scope(
            scope=request.scope_value,
            default_scope=context.get("buffer_scope", "run"),
            buffer_store=context.get("buffer_store"),
            buffer_store_registry=context.get("buffer_store_registry"),
        )
        variable_name = request.target
        display_name = f"variable: {variable_name}"
        if buffer_store is None:
            if request.required:
                return [self._skip_step_result(f"Required input variable not available: {variable_name}")]
            return [{
                "filepath": display_name,
                "filename": variable_name,
                "content": "",
                "found": False,
                "error": "Variable store unavailable",
                "images_policy": request.images_policy,
            }]
        entry = buffer_store.get(variable_name)
        if entry is None:
            if request.required:
                return [self._skip_step_result(f"Required input variable not found: {variable_name}")]
            return [{
                "filepath": display_name,
                "filename": variable_name,
                "content": "",
                "found": False,
                "error": "Variable not found",
                "images_policy": request.images_policy,
            }]

        content_value = entry.content or ""
        result = {
            "filepath": display_name,
            "filename": variable_name,
            "content": "" if request.refs_only else content_value,
            "found": True,
            "error": None,
            "images_policy": request.images_policy,
        }
        if request.refs_only:
            result["refs_only"] = True
        else:
            if request.properties_enabled:
                result = self._apply_properties_mode(result, request.properties_keys)
            if request.head_chars is not None or request.tail_chars is not None:
                result = self._truncate_result_content(
                    result,
                    head_chars=request.head_chars,
                    tail_chars=request.tail_chars,
                )
        return [result]

    def _apply_properties_mode(self, file_data: dict[str, Any], requested_keys: list[str] | None) -> dict[str, Any]:
        if not file_data.get("found", True):
            return file_data
        content = file_data.get("content")
        if not isinstance(content, str):
            return file_data
        try:
            props, _remaining = parse_simple_frontmatter(content, require_frontmatter=False)
        except ValueError:
            props = {}
        selected = dict(props) if requested_keys is None else {k: props[k] for k in requested_keys if k in props}
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

    def _truncate_result_content(
        self, file_data: dict[str, Any], *, head_chars: int | None, tail_chars: int | None
    ) -> dict[str, Any]:
        if not file_data.get("found", True) or file_data.get("refs_only"):
            return file_data
        content = file_data.get("content")
        if not isinstance(content, str):
            return file_data
        original_chars = len(content)
        file_data["content_original_chars"] = original_chars
        truncate_chars = head_chars if head_chars is not None else tail_chars
        if truncate_chars is None:
            return file_data
        if head_chars is not None:
            file_data["head"] = head_chars
        if tail_chars is not None:
            file_data["tail"] = tail_chars
        if original_chars <= truncate_chars:
            file_data["content_truncated"] = False
            return file_data
        file_data["content"] = content[:head_chars] if head_chars is not None else content[-tail_chars:]
        file_data["content_truncated"] = True
        return file_data

    def _apply_selector_mode(
        self,
        *,
        result_files: list[dict[str, Any]],
        input_expression: str,
        vault_path: str,
        selector_options: InputSelectorOptions | None,
        state_manager,
    ) -> list[dict[str, Any]]:
        candidate_paths: list[str] = []
        for file_data in result_files:
            if not isinstance(file_data, dict) or not file_data.get("found", True):
                continue
            source_path = file_data.get("source_path") or file_data.get("filepath")
            if not isinstance(source_path, str) or not source_path.strip():
                continue
            normalized_source = source_path.strip()
            if "." not in os.path.basename(normalized_source):
                normalized_source = f"{normalized_source}.md"
            candidate_path = normalized_source if os.path.isabs(normalized_source) else os.path.join(vault_path, normalized_source)
            if os.path.isdir(candidate_path):
                raise ValueError(
                    f"Input pattern '{input_expression}' resolved to directories; "
                    "use an explicit file pattern like 'projects/*/*.md' or 'projects/*/notes.md'"
                )
            if os.path.isfile(candidate_path):
                candidate_paths.append(candidate_path)
        if not candidate_paths:
            return [file_data for file_data in result_files if isinstance(file_data, dict)]

        selector = selector_options or InputSelectorOptions(
            mode=None, limit=None, order="alphanum", dir="asc", dt_pattern=None, dt_format=None
        )
        if selector.mode == "latest":
            sorted_paths = self.pattern_utils.sort_files(
                candidate_paths,
                order=selector.order,
                direction=selector.dir,
                filename_dt_pattern=selector.dt_pattern,
                filename_dt_format=selector.dt_format,
            )
            selected_paths = sorted_paths[: selector.limit]
        elif selector.mode == "pending":
            if state_manager:
                selected_paths = state_manager.get_pending_files(
                    candidate_paths,
                    self._build_pending_state_pattern(input_expression, selector),
                    selector.limit,
                    order=selector.order,
                    direction=selector.dir,
                    filename_dt_pattern=selector.dt_pattern,
                    filename_dt_format=selector.dt_format,
                )
            else:
                sorted_paths = self.pattern_utils.sort_files(
                    candidate_paths,
                    order=selector.order,
                    direction=selector.dir,
                    filename_dt_pattern=selector.dt_pattern,
                    filename_dt_format=selector.dt_format,
                )
                selected_paths = sorted_paths[: selector.limit]
        else:
            sorted_paths = self.pattern_utils.sort_files(
                candidate_paths,
                order=selector.order,
                direction=selector.dir,
                filename_dt_pattern=selector.dt_pattern,
                filename_dt_format=selector.dt_format,
            )
            selected_paths = sorted_paths if selector.limit is None else sorted_paths[: selector.limit]

        selected_results: list[dict[str, Any]] = []
        for file_path in selected_paths:
            relative_path = os.path.relpath(file_path, vault_path).replace("\\", "/")
            if relative_path.endswith(".md"):
                relative_path = relative_path[:-3]
            selected_results.append(load_file_with_metadata(relative_path, vault_path))

        if selector.mode == "pending" and selected_results:
            file_records = []
            for file_data in selected_results:
                if not file_data.get("found"):
                    continue
                source_path = str(file_data.get("source_path") or file_data.get("filepath") or "").strip()
                if source_path:
                    normalized_source = source_path if "." in os.path.basename(source_path) else f"{source_path}.md"
                    full_path = normalized_source if os.path.isabs(normalized_source) else os.path.join(vault_path, normalized_source)
                else:
                    full_path = ""
                if full_path and os.path.isfile(full_path):
                    content_hash = hash_file_bytes(full_path, length=None)
                elif file_data.get("content"):
                    content_hash = hash_file_content(file_data["content"], length=None)
                else:
                    continue
                if content_hash:
                    file_records.append({"content_hash": content_hash, "filepath": file_data["filepath"]})
            selected_results[0]["_state_metadata"] = {
                "requires_tracking": True,
                "pattern": self._build_pending_state_pattern(input_expression, selector),
                "file_records": file_records,
            }
        return selected_results

    def _build_pending_state_pattern(self, input_expression: str, selector_options: InputSelectorOptions) -> str:
        return (
            f"target={input_expression}|mode=pending|limit={selector_options.limit}"
            f"|order={selector_options.order}|dir={selector_options.dir}"
            f"|dt_pattern={selector_options.dt_pattern or ''}"
            f"|dt_format={selector_options.dt_format or ''}"
        )

    def _route_input_results(
        self,
        result_files: list[dict[str, Any]],
        output_target_value: str,
        write_mode_param: str | None,
        vault_path: str,
        context: dict[str, Any],
        refs_only: bool,
        scope_value: str | None,
    ) -> list[dict[str, Any]]:
        target_request = parse_output_value(
            output_target_value,
            allow_context=bool(context.get("allow_context_output")),
        )
        parsed_target = resolve_output_request(
            target_request,
            vault_path=vault_path,
            reference_date=context.get("reference_date"),
            week_start_day=context.get("week_start_day", 0),
            allow_context=bool(context.get("allow_context_output")),
        )
        if parsed_target.type == "inline":
            return result_files
        if parsed_target.type == "context":
            found_files = [f for f in result_files if isinstance(f, dict) and f.get("found", True)]
            combined_content = "\n".join(
                [f.get("filepath", "") for f in found_files if isinstance(f.get("filepath", ""), str)]
            ) if refs_only else "\n\n".join(
                [f.get("content", "") for f in found_files if isinstance(f.get("content", ""), str)]
            )
            manifest = build_manifest(
                source="input",
                destination="context",
                item_count=len(found_files),
                total_chars=len(combined_content),
                paths=[f.get("filepath") for f in found_files if f.get("filepath")] or None,
            )
            routed_results: list[dict[str, Any]] = []
            for file_data in result_files:
                if isinstance(file_data, dict):
                    file_data["refs_only"] = True
                    file_data["content"] = ""
                    file_data["routed_to"] = "context"
                routed_results.append(file_data)
            routed_results.append({"context_output": combined_content, "manifest": manifest, "found": True})
            return routed_results

        found_files = [f for f in result_files if isinstance(f, dict) and f.get("found", True)]
        write_mode = normalize_write_mode(write_mode_param)
        if write_mode == "new" and len(found_files) > 1:
            routed_results: list[dict[str, Any]] = []
            manifest_entries: list[dict[str, Any]] = []
            routed_destinations: dict[int, str] = {}
            for file_data in found_files:
                filepath = file_data.get("filepath") or file_data.get("filename") or "unknown"
                content_value = "" if refs_only else (file_data.get("content", "") or "")
                content_with_header = f"--- FILE: {filepath} ---\n{content_value}"
                write_result = write_output(
                    target=parsed_target.target,
                    content=content_with_header,
                    write_mode="new",
                    buffer_store=context.get("buffer_store"),
                    buffer_store_registry=context.get("buffer_store_registry"),
                    vault_path=vault_path,
                    buffer_scope=parsed_target.buffer_scope,
                    default_scope=context.get("buffer_scope", "run"),
                )
                destination = (
                    f"variable: {write_result.get('name')}" if write_result.get("type") == "buffer"
                    else f"file: {write_result.get('path')}" if write_result.get("type") == "file"
                    else parsed_target.type
                )
                routed_destinations[id(file_data)] = destination
                manifest_entries.append({
                    "manifest": build_manifest(
                        source="input",
                        destination=destination,
                        item_count=1,
                        total_chars=len(content_with_header),
                        paths=[filepath],
                        note="per-file routing (write-mode=new)",
                    ),
                    "found": True,
                })
            logger.set_sinks(["validation"]).info(
                "input_routed",
                data={
                    "event": "input_routed",
                    "destination": f"{parsed_target.type} (per-file, write-mode=new)",
                    "refs_only": refs_only,
                    "item_count": len(found_files),
                    "total_chars": sum(
                        len(f"--- FILE: {f.get('filepath') or f.get('filename') or 'unknown'} ---\n" + ("" if refs_only else (f.get("content", "") or "")))
                        for f in found_files
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

        combined_content = "\n".join(
            [f.get("filepath", "") for f in found_files if isinstance(f.get("filepath", ""), str)]
        ) if refs_only else "\n\n".join(
            [f.get("content", "") for f in found_files if isinstance(f.get("content", ""), str)]
        )
        write_result = write_output(
            target=parsed_target.target,
            content=combined_content,
            write_mode=write_mode,
            buffer_store=context.get("buffer_store"),
            buffer_store_registry=context.get("buffer_store_registry"),
            vault_path=vault_path,
            buffer_scope=parsed_target.buffer_scope,
            default_scope=context.get("buffer_scope", "run"),
        )
        destination = (
            f"variable: {write_result.get('name')}" if write_result.get("type") == "buffer"
            else f"file: {write_result.get('path')}" if write_result.get("type") == "file"
            else parsed_target.type
        )
        manifest = build_manifest(
            source="input",
            destination=destination,
            item_count=len(found_files),
            total_chars=len(combined_content),
            paths=[f.get("filepath") for f in found_files if f.get("filepath")] or None,
        )
        logger.set_sinks(["validation"]).info(
            "input_routed",
            data={
                "event": "input_routed",
                "destination": destination,
                "refs_only": refs_only,
                "item_count": len(found_files),
                "total_chars": len(combined_content),
            },
        )
        routed_results: list[dict[str, Any]] = []
        for file_data in result_files:
            if isinstance(file_data, dict):
                file_data["refs_only"] = True
                file_data["content"] = ""
                file_data["routed_to"] = destination
            routed_results.append(file_data)
        routed_results.append({"manifest": manifest, "found": True})
        return routed_results

    def _resolve_glob_pattern(self, glob_pattern: str, vault_path: str) -> list[dict[str, Any]]:
        if "**" in glob_pattern or ".." in glob_pattern:
            raise ValueError(f"Recursive or parent directory glob patterns not allowed: {glob_pattern}")
        matched_files = self.pattern_utils.resolve_safe_glob(glob_pattern, vault_path)
        result_files = []
        for file_path in matched_files:
            relative_path = os.path.relpath(file_path, vault_path)
            if relative_path.endswith(".md"):
                relative_path = relative_path[:-3]
            result_files.append(load_file_with_metadata(relative_path, vault_path))
        return result_files

    def _resolve_brace_pattern(self, value: str, vault_path: str, **context) -> list[dict[str, Any]]:
        brace_patterns = re.findall(r"\{([^}]+)\}", value)
        if len(brace_patterns) != 1:
            raise ValueError(f"Multiple time patterns not supported: {value}")
        pattern = brace_patterns[0]
        base_pattern, count = self.pattern_utils.parse_pattern_with_count(pattern)
        if count is None:
            base_pattern, _fmt = self.pattern_utils.parse_pattern_with_optional_format(pattern)
        if base_pattern == "pending":
            raise ValueError(
                "Legacy '{pending}' syntax is no longer supported. "
                "Use selector parameters, e.g. @input file: tasks/* (pending, limit=5)"
            )
        if base_pattern == "latest":
            raise ValueError(
                "Legacy '{latest}' syntax is no longer supported. "
                "Use selector parameters, e.g. @input file: journal/* (latest, limit=1)"
            )
        pattern_start = value.find(f"{{{pattern}}}")
        search_directory = os.path.join(vault_path, value[:pattern_start]) if pattern_start > 0 else vault_path
        if count is not None:
            return self._resolve_time_based_multi_pattern(
                base_pattern,
                count,
                search_directory,
                vault_path,
                context.get("reference_date"),
                context.get("week_start_day", 0),
            )
        return self._resolve_single_time_pattern(value, vault_path, **context)

    def _resolve_time_based_multi_pattern(
        self,
        base_pattern: str,
        count: int,
        search_directory: str,
        vault_path: str,
        reference_date: datetime | None,
        week_start_day: int,
    ) -> list[dict[str, Any]]:
        if count < 1:
            return []
        all_files = self.pattern_utils.get_directory_files(search_directory)
        if base_pattern == "latest":
            matched_files = self.pattern_utils.get_latest_files(all_files, count)
        elif base_pattern == "yesterday":
            now = reference_date or datetime.now()
            end_date = (now - timedelta(days=1)).date()
            start_date = (now - timedelta(days=count)).date()
            matched_files = self._select_files_in_date_range(all_files, start_date, end_date, limit=None)
        elif base_pattern in {"this-week", "last-week"}:
            now = reference_date or datetime.now()
            week_offset = 0 if base_pattern == "this-week" else -1
            week_start = self.pattern_utils._get_week_start_date(now, week_start_day, week_offset).date()
            matched_files = self._select_files_in_date_range(all_files, week_start, week_start + timedelta(days=6), limit=count)
        else:
            raise ValueError(f"Counted pattern '{{{base_pattern}:{count}}}' is not supported for @input")
        result_files = []
        for file_path in matched_files:
            relative_path = os.path.relpath(file_path, vault_path)
            if relative_path.endswith(".md"):
                relative_path = relative_path[:-3]
            result_files.append(load_file_with_metadata(relative_path, vault_path))
        return result_files

    def _select_files_in_date_range(self, all_files: list[str], start_date, end_date, limit: int | None) -> list[str]:
        dated_matches = []
        for filepath in all_files:
            file_date = self.pattern_utils.extract_date_from_filename(filepath)
            if not file_date:
                continue
            file_day = file_date.date()
            if start_date <= file_day <= end_date:
                dated_matches.append((file_date, filepath))
        dated_matches.sort(key=lambda x: x[0], reverse=True)
        matched_files = [filepath for _, filepath in dated_matches]
        return matched_files[:limit] if limit is not None else matched_files

    def _resolve_single_time_pattern(self, value: str, vault_path: str, **context) -> list[dict[str, Any]]:
        reference_date = context.get("reference_date")
        week_start_day = context.get("week_start_day", 0)
        brace_patterns = re.findall(r"\{([^}]+)\}", value)
        if not brace_patterns:
            return [load_file_with_metadata(value, vault_path)]
        pattern = brace_patterns[0]
        resolved_date = self.pattern_utils.resolve_date_pattern(pattern, reference_date, week_start_day)
        resolved_path = value.replace(f"{{{pattern}}}", resolved_date)
        if "*" in resolved_path:
            return self._resolve_glob_pattern(resolved_path, vault_path)
        return [load_file_with_metadata(resolved_path, vault_path)]


def _clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_positive_int_param(raw_value: Any, param_name: str) -> int | None:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(f"{param_name} must be a positive integer") from None
    if parsed <= 0:
        raise ValueError(f"{param_name} must be a positive integer")
    return parsed


def _parse_truncation_parameters(parameters: dict[str, Any]) -> tuple[int | None, int | None]:
    return _parse_positive_int_param(parameters.get("head"), "head"), _parse_positive_int_param(
        parameters.get("tail"), "tail"
    )


def _is_truthy_param(parameters: dict[str, Any], name: str) -> bool:
    if name not in parameters:
        return False
    raw = str(parameters.get(name, "true")).strip().lower()
    return raw in {"true", "yes", "1", "on"}


def _parse_properties_mode(properties_value: Any) -> tuple[bool, list[str] | None]:
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


def _parse_selector_options(parameters: dict[str, Any]) -> InputSelectorOptions:
    pending_enabled = _is_truthy_param(parameters, "pending")
    latest_enabled = _is_truthy_param(parameters, "latest")
    selector_mode = "pending" if pending_enabled else "latest" if latest_enabled else None
    raw_limit = str(parameters.get("limit") or "").strip()
    raw_order = str(parameters.get("order") or "").strip().lower()
    raw_dir = str(parameters.get("dir") or "").strip().lower()
    dt_pattern = _clean_optional_string(parameters.get("dt_pattern"))
    dt_format = _clean_optional_string(parameters.get("dt_format"))
    limit = None
    if raw_limit:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise ValueError("limit must be a positive integer") from None
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
    if selector_mode == "pending":
        raw_order = raw_order or "ctime"
        raw_dir = raw_dir or "asc"
        limit = 10 if limit is None else limit
        valid_orders = {"mtime", "ctime", "alphanum", "filename_dt"}
    elif selector_mode == "latest":
        raw_order = raw_order or "mtime"
        raw_dir = raw_dir or "desc"
        limit = 1 if limit is None else limit
        valid_orders = {"mtime", "ctime", "filename_dt"}
    else:
        raw_order = raw_order or "alphanum"
        raw_dir = raw_dir or "asc"
        valid_orders = {"mtime", "ctime", "alphanum", "filename_dt"}
    if raw_order not in valid_orders:
        allowed = ", ".join(sorted(valid_orders))
        raise ValueError(f"order must be one of: {allowed}")
    if raw_dir not in {"asc", "desc"}:
        raise ValueError("dir must be 'asc' or 'desc'")
    return InputSelectorOptions(
        mode=selector_mode,
        limit=limit,
        order=raw_order,
        dir=raw_dir,
        dt_pattern=dt_pattern,
        dt_format=dt_format,
    )


def _validate_parameter_combinations(*, target_type: str, parameters: dict[str, Any]) -> None:
    selection_param_keys = {"pending", "latest", "limit", "order", "dir", "dt_pattern", "dt_format"}
    if parameters.get("head") and parameters.get("tail"):
        raise ValueError("head and tail cannot be used together")
    if target_type == "variable" and any(key in parameters for key in selection_param_keys):
        raise ValueError(
            "Selection parameters (pending/latest/limit/order/dir/dt_*) "
            "are only supported for @input file targets"
        )
    pending_enabled = _is_truthy_param(parameters, "pending")
    latest_enabled = _is_truthy_param(parameters, "latest")
    if pending_enabled and latest_enabled:
        raise ValueError("Only one selector mode is supported: choose either pending or latest")
    selector_mode = "pending" if pending_enabled else "latest" if latest_enabled else None
    raw_order = str(parameters.get("order") or "").strip().lower()
    if raw_order:
        if selector_mode == "pending":
            valid_orders = {"mtime", "ctime", "alphanum", "filename_dt"}
        elif selector_mode == "latest":
            valid_orders = {"mtime", "ctime", "filename_dt"}
        else:
            valid_orders = {"mtime", "ctime", "alphanum", "filename_dt"}
        if raw_order not in valid_orders:
            allowed = ", ".join(sorted(valid_orders))
            raise ValueError(f"order '{raw_order}' is not supported for {selector_mode}; use: {allowed}")
    dt_pattern = str(parameters.get("dt_pattern") or "").strip()
    dt_format = str(parameters.get("dt_format") or "").strip()
    if raw_order == "filename_dt":
        if not dt_pattern or not dt_format:
            raise ValueError("filename_dt ordering requires dt_pattern and dt_format")
    elif dt_pattern or dt_format:
        raise ValueError("dt_pattern/dt_format require order=filename_dt")
