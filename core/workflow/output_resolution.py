"""Shared typed output resolution for workflow authoring surfaces."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.directives.parser import DirectiveValueParser
from core.directives.write_mode import WriteModeDirective
from core.utils.patterns import PatternUtilities
from core.utils.routing import OutputTarget, write_output


OUTPUT_ALLOWED_PARAMETERS = {"scope"}


@dataclass(frozen=True)
class OutputResolutionRequest:
    """Typed output target request."""

    target_type: str
    target: str | None = None
    scope_value: str | None = None


@dataclass(frozen=True)
class ResolvedOutputTarget:
    """Resolved output target ready for writing."""

    target: OutputTarget
    buffer_scope: str | None = None

    @property
    def type(self) -> str:
        return self.target.type

    @property
    def name(self) -> str | None:
        return self.target.name

    @property
    def path(self) -> str | None:
        return self.target.path

    def label(self) -> str:
        if self.type == "buffer":
            return f"variable:{self.name}"
        if self.type == "file":
            return f"file:{self.path}"
        return self.type


def normalize_write_mode(value: str | None) -> str | None:
    """Normalize write mode using the existing directive contract."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return WriteModeDirective().process_value(value, vault_path="")


def parse_output_value(
    value: Any,
    *,
    allow_context: bool = False,
) -> OutputResolutionRequest:
    """Parse legacy string/dict output expressions into a typed request."""
    if isinstance(value, ResolvedOutputTarget):
        target_type = value.type
        if target_type == "buffer":
            target_type = "variable"
        return OutputResolutionRequest(
            target_type=target_type,
            target=value.name if value.type == "buffer" else value.path,
            scope_value=value.buffer_scope,
        )

    if isinstance(value, dict):
        if value.get("type") == "context":
            if not allow_context:
                raise ValueError("Context output is not supported here")
            return build_output_request(target_type="context", target=None, parameters={})
        if value.get("type") == "buffer":
            return build_output_request(
                target_type="variable",
                target=value.get("name"),
                parameters={"scope": value.get("scope")},
            )
        if value.get("type") == "file":
            return build_output_request(target_type="file", target=value.get("path"), parameters={})
        if value.get("buffer"):
            return build_output_request(target_type="variable", target=value.get("buffer"), parameters={})
        if value.get("file"):
            return build_output_request(target_type="file", target=value.get("file"), parameters={})
        if value.get("type") in {"inline", "discard"}:
            return OutputResolutionRequest(target_type=value.get("type"))
        raise ValueError(f"Unsupported output target dict: {value}")

    if not value or not str(value).strip():
        raise ValueError("Output target cannot be empty")

    normalized = str(value).strip()
    lowered = normalized.lower()
    if lowered in {"inline", "discard"}:
        return OutputResolutionRequest(target_type=lowered)

    base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
        normalized,
        allowed_parameters=OUTPUT_ALLOWED_PARAMETERS,
    )
    return _request_from_base_value(base_value, parameters=parameters, allow_context=allow_context)


def build_output_request(
    *,
    target_type: str,
    target: Any,
    parameters: dict[str, Any] | None,
) -> OutputResolutionRequest:
    """Build a typed output request from structured authoring data."""
    normalized_type = str(target_type).strip().lower()
    normalized_params = {str(k).lower(): v for k, v in (parameters or {}).items()}

    if set(normalized_params) - OUTPUT_ALLOWED_PARAMETERS:
        raise ValueError("Output target does not accept parameters")

    scope_value = _clean_optional_string(normalized_params.get("scope"))

    if normalized_type == "context":
        if target not in {None, ""}:
            raise ValueError("Context output does not accept a target value")
        if scope_value:
            raise ValueError("Context output does not accept parameters")
        return OutputResolutionRequest(target_type="context")

    if normalized_type == "variable":
        name = _clean_required_string(target, "Variable name is required for variable output")
        return OutputResolutionRequest(target_type="variable", target=name, scope_value=scope_value)

    if normalized_type == "file":
        if scope_value:
            raise ValueError("Scope is only supported for variable outputs")
        path = _clean_required_string(target, "Output path is required for file output")
        if path.startswith("/") or ".." in path:
            raise ValueError("Output file path must stay within the vault")
        return OutputResolutionRequest(target_type="file", target=path)

    if normalized_type in {"inline", "discard"}:
        return OutputResolutionRequest(target_type=normalized_type)

    raise ValueError("Output target must be file, variable, context, inline, or discard")


def resolve_output_request(
    request: OutputResolutionRequest,
    *,
    vault_path: str,
    reference_date: datetime | None = None,
    week_start_day: int = 0,
    allow_context: bool = False,
) -> ResolvedOutputTarget:
    """Resolve a typed request into a concrete write target."""
    if reference_date is None:
        reference_date = datetime.now()

    if request.target_type == "context":
        if not allow_context:
            raise ValueError("Context output is not supported here")
        return ResolvedOutputTarget(target=OutputTarget(type="context"))

    if request.target_type in {"inline", "discard"}:
        return ResolvedOutputTarget(target=OutputTarget(type=request.target_type))

    if request.target_type == "variable":
        return ResolvedOutputTarget(
            target=OutputTarget(type="buffer", name=request.target),
            buffer_scope=request.scope_value,
        )

    if request.target_type != "file":
        raise ValueError("Output target must be file, variable, context, inline, or discard")

    value = request.target or ""
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2]
    resolved_path = _resolve_output_path(
        value,
        vault_path=vault_path,
        reference_date=reference_date,
        week_start_day=week_start_day,
    )
    return ResolvedOutputTarget(target=OutputTarget(type="file", path=resolved_path))


def resolve_header_value(
    value: str,
    *,
    reference_date: datetime | None = None,
    week_start_day: int = 0,
) -> str:
    """Resolve shared header template patterns."""
    if not value or not value.strip():
        raise ValueError("Header value cannot be empty")
    if reference_date is None:
        reference_date = datetime.now()
    return _resolve_header_text(value.strip(), reference_date=reference_date, week_start_day=week_start_day)


def write_resolved_output(
    *,
    resolved_target: ResolvedOutputTarget,
    content: str,
    write_mode: str | None,
    vault_path: str | None,
    buffer_store=None,
    buffer_store_registry: dict[str, Any] | None = None,
    header: str | None = None,
    metadata: dict[str, Any] | None = None,
    default_scope: str = "run",
) -> dict[str, Any]:
    """Write to a previously resolved target using the shared sink path."""
    return write_output(
        target=resolved_target.target,
        content=content,
        write_mode=write_mode,
        buffer_store=buffer_store,
        buffer_store_registry=buffer_store_registry,
        vault_path=vault_path,
        header=header,
        metadata=metadata,
        buffer_scope=resolved_target.buffer_scope,
        default_scope=default_scope,
    )


def _request_from_base_value(
    base_value: str,
    *,
    parameters: dict[str, Any],
    allow_context: bool,
) -> OutputResolutionRequest:
    if not base_value:
        raise ValueError("Output target cannot be empty")

    if base_value == "context":
        if not allow_context:
            raise ValueError("Context output is not supported here")
        return build_output_request(target_type="context", target=None, parameters=parameters)

    if base_value.startswith("variable:"):
        return build_output_request(
            target_type="variable",
            target=base_value[len("variable:") :].strip(),
            parameters=parameters,
        )

    if base_value.startswith("file:"):
        return build_output_request(
            target_type="file",
            target=base_value[len("file:") :].strip(),
            parameters=parameters,
        )

    raise ValueError("Output target must start with file: or variable:")


def _resolve_output_path(
    value: str,
    *,
    vault_path: str,
    reference_date: datetime,
    week_start_day: int,
) -> str:
    brace_patterns = re.findall(r"\{([^}]+)\}", value)
    if not brace_patterns:
        return _normalize_markdown_extension(value)

    pattern_utils = PatternUtilities()
    resolved_path = value
    for pattern in brace_patterns:
        base_pattern, count = pattern_utils.parse_pattern_with_count(pattern)
        if count is None:
            base_pattern, _fmt = pattern_utils.parse_pattern_with_optional_format(pattern)

        if base_pattern == "pending":
            raise ValueError("'{pending}' pattern not supported in @output directive")
        if count is not None:
            raise ValueError(f"Multi-file pattern '{pattern}' not supported in @output directive")

        resolved_value = _resolve_output_pattern(
            pattern,
            vault_path=vault_path,
            reference_date=reference_date,
            week_start_day=week_start_day,
            pattern_utils=pattern_utils,
        )
        resolved_path = resolved_path.replace(f"{{{pattern}}}", resolved_value)

    return _normalize_markdown_extension(resolved_path)


def _resolve_output_pattern(
    pattern: str,
    *,
    vault_path: str,
    reference_date: datetime,
    week_start_day: int,
    pattern_utils: PatternUtilities,
) -> str:
    base_pattern, fmt = pattern_utils.parse_pattern_with_optional_format(pattern)

    if base_pattern in {
        "today",
        "yesterday",
        "tomorrow",
        "this-week",
        "last-week",
        "next-week",
        "this-month",
        "last-month",
        "day-name",
        "month-name",
    }:
        return pattern_utils.resolve_date_pattern(pattern, reference_date, week_start_day)

    if base_pattern == "latest":
        if fmt is not None:
            return pattern
        return _find_latest_file_date(
            vault_path=vault_path,
            reference_date=reference_date,
            pattern_utils=pattern_utils,
        )

    return pattern


def _find_latest_file_date(
    *,
    vault_path: str,
    reference_date: datetime,
    pattern_utils: PatternUtilities,
) -> str:
    try:
        all_files = pattern_utils.get_directory_files(vault_path)
        if all_files:
            latest_files = pattern_utils.get_latest_files(all_files, 1)
            if latest_files:
                file_date = pattern_utils.extract_date_from_filename(latest_files[0])
                if file_date:
                    return file_date.strftime("%Y-%m-%d")
    except Exception:
        pass
    return reference_date.strftime("%Y-%m-%d")


def _resolve_header_text(
    value: str,
    *,
    reference_date: datetime,
    week_start_day: int,
) -> str:
    pattern_utils = PatternUtilities()
    brace_patterns = re.findall(r"\{([^}]+)\}", value)
    if not brace_patterns:
        return value

    resolved_header = value
    for pattern in brace_patterns:
        base_pattern, count = pattern_utils.parse_pattern_with_count(pattern)
        if count is None:
            base_pattern, _fmt = pattern_utils.parse_pattern_with_optional_format(pattern)

        if base_pattern == "pending":
            raise ValueError("'{pending}' pattern not supported in @header directive")
        if count is not None:
            raise ValueError(f"Multi-file pattern '{pattern}' not supported in @header directive")

        if base_pattern in {
            "today",
            "yesterday",
            "tomorrow",
            "this-week",
            "last-week",
            "next-week",
            "this-month",
            "last-month",
            "day-name",
            "month-name",
        }:
            replacement = pattern_utils.resolve_date_pattern(pattern, reference_date, week_start_day)
        else:
            replacement = pattern
        resolved_header = resolved_header.replace(f"{{{pattern}}}", replacement)
    return resolved_header


def _normalize_markdown_extension(file_path: str) -> str:
    if file_path.endswith(".md"):
        return file_path
    base_name = os.path.basename(file_path)
    if "." in base_name:
        path_parts = file_path.rsplit(".", 1)
        return f"{path_parts[0]}.md"
    return f"{file_path}.md"


def _clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _clean_required_string(value: Any, error_message: str) -> str:
    cleaned = _clean_optional_string(value)
    if cleaned is None:
        raise ValueError(error_message)
    return cleaned
