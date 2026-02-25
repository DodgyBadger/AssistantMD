from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    BuiltinToolReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

from core.context.templates import TemplateRecord, TemplateSection
from core.constants import CONTEXT_MANAGER_SYSTEM_INSTRUCTION, VALID_WEEK_DAYS
from core.context.store import (
    get_cached_step_output,
    get_recent_summaries,
    upsert_cached_step_output,
)
from core.directives.context_manager import _parse_passthrough_runs
from core.directives.tools import ToolsDirective
from core.logger import UnifiedLogger
from core.chunking import build_input_files_prompt
from core.llm.model_utils import model_supports_capability
from core.runtime.buffers import BufferStore
from core.runtime.state import get_runtime_context, has_runtime_context
from core.utils.hash import hash_file_content
from core.utils.routing import OutputTarget, format_input_files_block, write_output
from core.context.manager_types import (
    ContextManagerDeps,
    ContextManagerInput,
    ContextManagerResult,
    CacheDecision,
    ContextTemplateError,
    InputResolutionResult,
    OutputRoutingResult,
    SectionExecutionContext,
    SectionExecutionResult,
)

logger = UnifiedLogger(tag="context-manager")


def _raise_context_template_error(
    *,
    message: str,
    section_name: str,
    phase: str,
    pointer_suffix: str,
    cause: Exception | None = None,
) -> None:
    if isinstance(cause, ContextTemplateError):
        raise cause
    pointer = f"## {section_name} ({pointer_suffix})"
    if cause is not None:
        raise ContextTemplateError(
            message,
            template_pointer=pointer,
            section_name=section_name,
            phase=phase,
        ) from cause
    raise ContextTemplateError(
        message,
        template_pointer=pointer,
        section_name=section_name,
        phase=phase,
    )


@dataclass
class ContextTemplateRuntime:
    """Resolved template configuration for a context manager run."""

    template: TemplateRecord
    sections: List[TemplateSection]
    week_start_day: int
    passthrough_runs: int
    token_threshold: int
    chat_instruction_message: Optional[ModelMessage]


def build_chat_instruction_message(chat_instructions: Optional[str]) -> Optional[ModelMessage]:
    if not chat_instructions:
        return None
    return ModelRequest(parts=[SystemPromptPart(content=chat_instructions)])


def prepare_template_runtime(
    template: TemplateRecord,
    passthrough_runs_default: int,
    token_threshold_default: int = 0,
) -> ContextTemplateRuntime:
    template_directives = template.directives or {}
    template_sections = template.template_sections or []
    week_start_day = resolve_week_start_day(template.frontmatter)
    chat_instructions = (template.chat_instructions or "").strip() or None
    passthrough_runs = resolve_passthrough_runs(template.frontmatter, passthrough_runs_default)
    chat_instruction_message = build_chat_instruction_message(chat_instructions)
    token_threshold = resolve_token_threshold(template.frontmatter, token_threshold_default)
    if template_sections:
        sections = template_sections
    elif template.template_body:
        sections = [
            TemplateSection(
                name=template.template_section or "Template",
                content=template.template_body or "",
                cleaned_content=template.template_body or "",
                directives=template_directives,
            )
        ]
    else:
        sections = []
    return ContextTemplateRuntime(
        template=template,
        sections=sections,
        week_start_day=week_start_day,
        passthrough_runs=passthrough_runs,
        token_threshold=token_threshold,
        chat_instruction_message=chat_instruction_message,
    )


def normalize_input_file_lists(input_file_data: Any) -> List[List[Dict[str, Any]]]:
    if not input_file_data:
        return []
    if isinstance(input_file_data, list) and input_file_data and isinstance(input_file_data[0], dict):
        return [input_file_data]
    if isinstance(input_file_data, list):
        return input_file_data
    return []


def count_input_files(input_file_data: Any) -> Dict[str, int]:
    file_lists = normalize_input_file_lists(input_file_data)
    if not file_lists:
        return {"total": 0, "refs_only": 0, "missing": 0}
    total = 0
    refs_only = 0
    missing = 0
    for file_list in file_lists:
        for file_data in file_list:
            if not isinstance(file_data, dict):
                continue
            if file_data.get("manifest"):
                continue
            total += 1
            if file_data.get("refs_only"):
                refs_only += 1
            if file_data.get("found") is False:
                missing += 1
    return {"total": total, "refs_only": refs_only, "missing": missing}


def summarize_input_files(input_file_data: Any, preview_limit: int = 200) -> List[Dict[str, Any]]:
    file_lists = normalize_input_file_lists(input_file_data)
    if not file_lists:
        return []
    summaries: List[Dict[str, Any]] = []
    for file_list in file_lists:
        for file_data in file_list:
            if not isinstance(file_data, dict):
                continue
            if file_data.get("manifest"):
                continue
            content = ""
            if file_data.get("found") and not file_data.get("refs_only"):
                content = file_data.get("content", "") or ""
            preview = None
            if content:
                preview = content.strip().replace("\n", " ")
                if len(preview) > preview_limit:
                    preview = f"{preview[:preview_limit - 1]}…"
            summaries.append(
                {
                    "filepath": file_data.get("filepath"),
                    "found": file_data.get("found", True),
                    "refs_only": file_data.get("refs_only", False),
                    "content_length": len(content),
                    "content_preview": preview,
                }
            )
    return summaries


def hash_output(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hash_file_content(value, length=12)


def resolve_cache_now(run_context: RunContext[Any]) -> datetime:
    deps = getattr(run_context, "deps", None)
    now_override = getattr(deps, "context_manager_now", None) if deps is not None else None
    if isinstance(now_override, datetime):
        return now_override
    if isinstance(now_override, str):
        try:
            return datetime.fromisoformat(now_override)
        except ValueError:
            pass
    if has_runtime_context():
        try:
            runtime = get_runtime_context()
            raw_value = (runtime.config.features or {}).get("context_manager_now")
            if isinstance(raw_value, datetime):
                return raw_value
            if isinstance(raw_value, str):
                return datetime.fromisoformat(raw_value)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def format_input_files_for_prompt(
    input_file_data: Any,
    has_empty_directive: bool = False,
) -> Optional[str]:
    return format_input_files_block(
        input_file_data,
        has_empty_directive=has_empty_directive,
    )


def has_empty_input_file_directive(content: str) -> bool:
    if not content:
        return False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("@input"):
            return stripped in ("@input", "@input:")
    return False


def _frontmatter_value_with_alias(
    frontmatter: Optional[Dict[str, Any]],
    canonical_key: str,
    alias_key: str,
) -> Any:
    """Get a frontmatter value supporting both canonical and alias keys."""
    if not frontmatter:
        return None

    canonical_present = canonical_key in frontmatter
    alias_present = alias_key in frontmatter
    canonical_value = frontmatter.get(canonical_key)
    alias_value = frontmatter.get(alias_key)

    if canonical_present and alias_present and canonical_value != alias_value:
        logger.warning(
            "Conflicting frontmatter keys; preferring canonical key",
            metadata={
                "canonical_key": canonical_key,
                "alias_key": alias_key,
                "canonical_value": canonical_value,
                "alias_value": alias_value,
            },
        )

    if canonical_present:
        return canonical_value
    if alias_present:
        return alias_value
    return None


def resolve_week_start_day(frontmatter: Optional[Dict[str, Any]]) -> int:
    """
    Resolve week_start_day from template frontmatter.

    Returns 0=Monday .. 6=Sunday, defaulting to Monday on missing/invalid values.
    """
    if not frontmatter:
        return 0
    raw_value = _frontmatter_value_with_alias(frontmatter, "week_start_day", "week-start-day")
    if raw_value is None:
        return 0
    if isinstance(raw_value, int) and 0 <= raw_value <= 6:
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in VALID_WEEK_DAYS:
            return VALID_WEEK_DAYS.index(normalized)
    logger.warning(
        "Invalid week_start_day in context template; defaulting to monday",
        metadata={"value": raw_value},
    )
    return 0


def parse_db_timestamp(raw_value: Optional[str]) -> Optional[datetime]:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        try:
            return datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None


def start_of_week(value: datetime, week_start_day: int) -> datetime:
    delta_days = (value.weekday() - week_start_day) % 7
    return (value - timedelta(days=delta_days)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def cache_entry_is_valid(
    *,
    created_at: Optional[str],
    cache_mode: str,
    ttl_seconds: Optional[int],
    now: datetime,
    week_start_day: int,
) -> bool:
    created_dt = parse_db_timestamp(created_at)
    if created_dt is None:
        return False
    if created_dt.tzinfo is None and now.tzinfo is not None:
        created_dt = created_dt.replace(tzinfo=timezone.utc)
    elif created_dt.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if cache_mode == "duration":
        if ttl_seconds is None:
            return False
        return now - created_dt < timedelta(seconds=ttl_seconds)
    if cache_mode == "daily":
        return created_dt.date() == now.date()
    if cache_mode == "weekly":
        return start_of_week(created_dt, week_start_day) == start_of_week(now, week_start_day)
    if cache_mode == "session":
        return True
    return False


def resolve_passthrough_runs(frontmatter: Optional[Dict[str, Any]], default: int) -> int:
    if not frontmatter:
        return default
    raw_value = _frontmatter_value_with_alias(frontmatter, "passthrough_runs", "passthrough-runs")
    if raw_value is None:
        return default
    if isinstance(raw_value, int):
        if raw_value < -1:
            logger.warning(
                "Invalid passthrough_runs in context template; defaulting",
                metadata={"value": raw_value},
            )
            return default
        return raw_value
    if isinstance(raw_value, str):
        try:
            return _parse_passthrough_runs(raw_value)
        except Exception:
            logger.warning(
                "Invalid passthrough_runs in context template; defaulting",
                metadata={"value": raw_value},
            )
            return default
    logger.warning(
        "Invalid passthrough_runs in context template; defaulting",
        metadata={"value": raw_value},
    )
    return default


def resolve_token_threshold(frontmatter: Optional[Dict[str, Any]], default: int) -> int:
    if not frontmatter:
        return default
    raw_value = _frontmatter_value_with_alias(frontmatter, "token_threshold", "token-threshold")
    if raw_value is None:
        return default
    if isinstance(raw_value, int):
        if raw_value < 0:
            logger.warning(
                "Invalid token_threshold in context template; defaulting",
                metadata={"value": raw_value},
            )
            return default
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = int(raw_value.strip())
        except ValueError:
            logger.warning(
                "Invalid token_threshold in context template; defaulting",
                metadata={"value": raw_value},
            )
            return default
        if parsed < 0:
            logger.warning(
                "Invalid token_threshold in context template; defaulting",
                metadata={"value": raw_value},
            )
            return default
        return parsed
    logger.warning(
        "Invalid token_threshold in context template; defaulting",
        metadata={"value": raw_value},
    )
    return default


def run_slice(msgs: List[ModelMessage], runs_to_take: int) -> List[ModelMessage]:
    run_ids: List[str] = []
    for m in msgs:
        rid = getattr(m, "run_id", None)
        if rid:
            if not run_ids or run_ids[-1] != rid:
                run_ids.append(rid)
    if run_ids:
        if runs_to_take == 0:
            return []
        take_runs = runs_to_take if runs_to_take > 0 else len(run_ids)
        selected_run_ids = set(run_ids[-take_runs:])
        start_idx = 0
        for idx, m in enumerate(msgs):
            if getattr(m, "run_id", None) in selected_run_ids:
                start_idx = idx
                break
        return msgs[start_idx:]
    # Fallback: slice from last user message to end (user→assistant→tools)
    last_user_idx = None
    for idx in range(len(msgs) - 1, -1, -1):
        m = msgs[idx]
        role = getattr(m, "role", None)
        if role and role.lower() == "user":
            last_user_idx = idx
            break
        if isinstance(m, ModelRequest):
            last_user_idx = idx
            break
    if last_user_idx is not None:
        return msgs[last_user_idx:]
    return msgs


def find_last_user_idx(msgs: List[ModelMessage]) -> Optional[int]:
    for idx in range(len(msgs) - 1, -1, -1):
        m = msgs[idx]
        role = getattr(m, "role", None)
        if role and role.lower() == "user":
            return idx
        if isinstance(m, ModelRequest):
            return idx
    return None


def extract_role_and_text(msg: ModelMessage) -> tuple[str, str]:
    # Normalize role names across message types
    if isinstance(msg, ModelRequest):
        role = "user"
    elif isinstance(msg, ModelResponse):
        role = "assistant"
    else:
        role = getattr(msg, "role", None) or msg.__class__.__name__.lower()

    parts = getattr(msg, "parts", None)
    if parts:
        has_system_part = False
        rendered_parts: List[str] = []
        for part in parts:
            if isinstance(part, (UserPromptPart, TextPart)):
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(part_content)
            elif isinstance(part, SystemPromptPart):
                has_system_part = True
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(part_content)
            elif isinstance(part, (ToolReturnPart, BuiltinToolReturnPart)):
                tool_name = getattr(part, "tool_name", None) or getattr(part, "tool_call_id", None) or "tool"
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(f"[{tool_name}] {part_content}")
            elif isinstance(part, ToolCallPart):
                tool_name = getattr(part, "tool_name", None) or getattr(part, "tool_call_id", None) or "tool"
                rendered_parts.append(f"[{tool_name}] (tool call)")
        if rendered_parts:
            if has_system_part and role == "user":
                return "system", "\n".join(rendered_parts)
            return role, "\n".join(rendered_parts)

    # Try direct content if no parts were rendered
    content = getattr(msg, "content", None)
    if isinstance(content, str) and content:
        return role, content

    return role, ""


def resolve_section_int(
    *,
    registry: Any,
    directive_key: str,
    section_directives: Dict[str, List[str]],
    vault_path: str,
    section_name: str,
    default: int = 0,
) -> int:
    values = section_directives.get(directive_key, [])
    if not values and "_" in directive_key:
        values = section_directives.get(directive_key.replace("_", "-"), [])
    if not values and "-" in directive_key:
        values = section_directives.get(directive_key.replace("-", "_"), [])
    if values:
        try:
            result = registry.process_directive(
                directive_key,
                values[-1],
                vault_path,
            )
            if not result.success:
                _raise_context_template_error(
                    message=f"Invalid @{directive_key} value: {result.error_message}",
                    section_name=section_name,
                    phase="directive_parse",
                    pointer_suffix=f"@{directive_key} directive",
                )
            return int(result.processed_value)
        except Exception as exc:
            _raise_context_template_error(
                message=f"Failed to process @{directive_key}: {exc}",
                section_name=section_name,
                phase="directive_parse",
                pointer_suffix=f"@{directive_key} directive",
                cause=exc,
            )
    return default


def resolve_section_header(
    *,
    registry: Any,
    section_directives: Dict[str, List[str]],
    vault_path: str,
    week_start_day: int,
    section_name: str,
) -> Optional[str]:
    header_values = section_directives.get("header", [])
    if not header_values:
        return None
    try:
        header_result = registry.process_directive(
            "header",
            header_values[-1],
            vault_path,
            reference_date=datetime.now(),
            week_start_day=week_start_day,
        )
        if header_result.success:
            return header_result.processed_value
        _raise_context_template_error(
            message=f"Invalid @header value: {header_result.error_message}",
            section_name=section_name,
            phase="directive_parse",
            pointer_suffix="@header directive",
        )
    except Exception as exc:
        _raise_context_template_error(
            message=f"Failed to process @header: {exc}",
            section_name=section_name,
            phase="directive_parse",
            pointer_suffix="@header directive",
            cause=exc,
        )
    return None


def resolve_section_write_mode(
    *,
    registry: Any,
    section_directives: Dict[str, List[str]],
    vault_path: str,
    section_name: str,
) -> Optional[str]:
    write_mode_values = section_directives.get("write_mode", [])
    if not write_mode_values:
        write_mode_values = section_directives.get("write-mode", [])
    if not write_mode_values:
        return None
    try:
        write_mode_result = registry.process_directive(
            "write_mode",
            write_mode_values[-1],
            vault_path,
        )
        if write_mode_result.success:
            return write_mode_result.processed_value
        _raise_context_template_error(
            message=f"Invalid @write_mode value: {write_mode_result.error_message}",
            section_name=section_name,
            phase="directive_parse",
            pointer_suffix="@write_mode directive",
        )
    except Exception as exc:
        _raise_context_template_error(
            message=f"Failed to process @write_mode: {exc}",
            section_name=section_name,
            phase="directive_parse",
            pointer_suffix="@write_mode directive",
            cause=exc,
        )
    return None


def resolve_section_outputs(
    *,
    registry: Any,
    section_directives: Dict[str, List[str]],
    vault_path: str,
    week_start_day: int,
    session_id: str,
    vault_name: str,
    section_name: str,
) -> List[Any]:
    output_targets: List[Any] = []
    output_values = section_directives.get("output", [])
    if not output_values:
        return output_targets
    for output_value in output_values:
        try:
            output_result = registry.process_directive(
                "output",
                output_value,
                vault_path,
                reference_date=datetime.now(),
                week_start_day=week_start_day,
            )
            if output_result.success:
                output_target = output_result.processed_value
                output_targets.append(output_target)
                if isinstance(output_target, dict) and output_target.get("type") == "buffer":
                    logger.info(
                        "Context output target resolved (buffer)",
                        data={
                            "session_id": session_id,
                            "vault_name": vault_name,
                            "section_name": section_name,
                            "variable": output_target.get("name"),
                        },
                    )
                elif isinstance(output_target, dict) and output_target.get("type") == "context":
                    logger.info(
                        "Context output target resolved (context)",
                        data={
                            "session_id": session_id,
                            "vault_name": vault_name,
                            "section_name": section_name,
                        },
                    )
                elif isinstance(output_target, str):
                    logger.info(
                        "Context output target resolved (file)",
                        data={
                            "session_id": session_id,
                            "vault_name": vault_name,
                            "section_name": section_name,
                            "output_file": output_target,
                        },
                    )
        except Exception as exc:
            _raise_context_template_error(
                message=f"Failed to process @output '{output_value}': {exc}",
                section_name=section_name,
                phase="directive_parse",
                pointer_suffix="@output directive",
                cause=exc,
            )
    return output_targets


def resolve_section_cache_config(
    *,
    registry: Any,
    section_directives: Dict[str, List[str]],
    vault_path: str,
    section_name: str,
) -> Optional[Dict[str, Any]]:
    cache_values = section_directives.get("cache", [])
    if not cache_values:
        return None
    try:
        result = registry.process_directive(
            "cache",
            cache_values[-1],
            vault_path,
        )
        if not result.success:
            _raise_context_template_error(
                message=f"Invalid @cache value: {result.error_message}",
                section_name=section_name,
                phase="directive_parse",
                pointer_suffix="@cache directive",
            )
        return result.processed_value
    except Exception as exc:
        _raise_context_template_error(
            message=f"Failed to process @cache: {exc}",
            section_name=section_name,
            phase="directive_parse",
            pointer_suffix="@cache directive",
            cause=exc,
        )
    return None


def resolve_section_tools(
    *,
    section_directives: Dict[str, List[str]],
    vault_path: str,
    section_name: str,
) -> Tuple[Optional[List[Any]], str]:
    tools_values = section_directives.get("tools", [])
    if not tools_values:
        return None, ""
    try:
        tools_directive = ToolsDirective()
        tools_results = [
            tools_directive.process_value(value, vault_path=vault_path)
            for value in tools_values
        ]
        tools_for_manager, tool_instructions, _ = ToolsDirective.merge_results(tools_results)
        return tools_for_manager, tool_instructions or ""
    except Exception as exc:
        _raise_context_template_error(
            message=f"Failed to process @tools: {exc}",
            section_name=section_name,
            phase="directive_parse",
            pointer_suffix="@tools directive",
            cause=exc,
        )
    return None, ""


def resolve_section_inputs(
    *,
    registry: Any,
    section: TemplateSection,
    vault_path: str,
    week_start_day: int,
    run_buffer_store: BufferStore,
    buffer_store_registry: dict[str, BufferStore],
    session_id: str,
    vault_name: str,
    section_key: str,
    section_name: str,
    model_alias: str,
) -> InputResolutionResult:
    section_directives = section.directives or {}
    input_file_values = section_directives.get("input", [])
    empty_input_file_directive = has_empty_input_file_directive(section.content)
    input_file_data = None
    context_input_outputs: List[str] = []
    skipped_required = False
    if input_file_values:
        processed_values: List[Any] = []
        for value in input_file_values:
            try:
                result = registry.process_directive(
                    "input",
                    value,
                    vault_path,
                    # TODO: use centralized time manager once available for consistency with workflows.
                    reference_date=datetime.now(),
                    week_start_day=week_start_day,
                    state_manager=None,
                    buffer_store=run_buffer_store,
                    buffer_store_registry=buffer_store_registry,
                    buffer_scope="run",
                    allow_context_output=True,
                )
            except Exception as exc:
                _raise_context_template_error(
                    message=f"Failed to process @input '{value}': {exc}",
                    section_name=section_name,
                    phase="directive_parse",
                    pointer_suffix="@input directive",
                    cause=exc,
                )
            if not result.success:
                _raise_context_template_error(
                    message=f"Invalid @input value: {result.error_message}",
                    section_name=section_name,
                    phase="directive_parse",
                    pointer_suffix="@input directive",
                )
            if isinstance(result.processed_value, list):
                if any(
                    item.get("_workflow_signal") == "skip_step"
                    for item in result.processed_value
                    if isinstance(item, dict)
                ):
                    processed_values = []
                    input_file_data = None
                    skipped_required = True
                    logger.info(
                        "Skipping context section due to required input directive",
                        metadata={"section": section.name},
                    )
                    break
                for item in result.processed_value:
                    if isinstance(item, dict) and item.get("context_output"):
                        context_input_outputs.append(
                            item.get("context_output", "")
                        )
            processed_values.append(result.processed_value)
        if processed_values:
            input_file_data = processed_values[0] if len(processed_values) == 1 else processed_values
        elif input_file_data is None and processed_values == [] and skipped_required:
            logger.set_sinks(["validation"]).info(
                "Context section skipped (input required)",
                data={
                    "event": "context_section_skipped",
                    "section_name": section.name,
                    "section_key": section_key,
                    "reason": "input_file_required",
                },
            )
            return InputResolutionResult(
                input_file_data=None,
                input_files_prompt=None,
                context_input_outputs=[],
                empty_input_file_directive=empty_input_file_directive,
                skip_required=True,
            )

    if input_file_values:
        counts = count_input_files(input_file_data)
        file_summaries = summarize_input_files(input_file_data)
        logger.set_sinks(["validation"]).info(
            "Context input files resolved",
            data={
                "event": "context_input_files_resolved",
                "section_name": section.name,
                "section_key": section_key,
                "file_count": counts["total"],
                "refs_only_count": counts["refs_only"],
                "missing_count": counts["missing"],
                "files": file_summaries,
            },
        )
        if file_summaries:
            logger.info(
                "Context input files resolved",
                data={
                    "session_id": session_id,
                    "vault_name": vault_name,
                    "section_name": section.name,
                    "file_count": counts["total"],
                    "refs_only_count": counts["refs_only"],
                    "missing_count": counts["missing"],
                    "files": file_summaries,
                },
            )
    input_files_prompt = None
    if input_file_data or empty_input_file_directive:
        supports_vision = model_supports_capability(model_alias, "vision")
        built_prompt = build_input_files_prompt(
            input_file_data=input_file_data,
            vault_path=vault_path,
            has_empty_directive=empty_input_file_directive and not input_file_data,
            supports_vision=supports_vision,
        )
        input_files_prompt = built_prompt.prompt

    return InputResolutionResult(
        input_file_data=input_file_data,
        input_files_prompt=input_files_prompt,
        context_input_outputs=context_input_outputs,
        empty_input_file_directive=empty_input_file_directive,
        skip_required=False,
    )




def resolve_cache_decision(
    *,
    section: TemplateSection,
    section_key: str,
    skip_llm: bool,
    cache_config: Optional[Dict[str, Any]],
    exec_ctx: SectionExecutionContext,
) -> CacheDecision:
    managed_output: Optional[str] = None
    managed_model_alias: str = exec_ctx.model_alias
    cache_hit_scope: Optional[str] = None
    cache_mode: Optional[str] = None

    section_cache_entry = exec_ctx.section_cache.get(section_key, {})
    managed_output = section_cache_entry.get("raw_output")
    managed_model_alias = section_cache_entry.get("model_alias", exec_ctx.model_alias)
    if exec_ctx.cache_enabled and managed_output is not None:
        cache_hit_scope = "run"
        cached_hash = hash_output(managed_output)
        logger.set_sinks(["validation"]).info(
            "Context cache hit (run)",
            data={
                "event": "context_cache_hit",
                "section_name": section.name,
                "section_key": section_key,
                "cache_scope": cache_hit_scope,
                "output_hash": cached_hash,
            },
        )
    elif not exec_ctx.cache_enabled:
        managed_output = None

    if cache_config and not cache_mode:
        cache_mode = cache_config.get("mode")

    if not skip_llm and exec_ctx.cache_enabled and managed_output is None and cache_config:
        ttl_seconds = cache_config.get("ttl_seconds")
        if cache_mode:
            cached_entry = get_cached_step_output(
                session_id=exec_ctx.session_id,
                vault_name=exec_ctx.vault_name,
                template_name=exec_ctx.template.name,
                section_key=section_key,
                cache_mode=cache_mode,
            )
            cache_reason = None
            if cached_entry and cached_entry.get("template_hash") == exec_ctx.template.sha256:
                now = resolve_cache_now(exec_ctx.run_context)
                if cache_entry_is_valid(
                    created_at=cached_entry.get("created_at"),
                    cache_mode=cache_mode,
                    ttl_seconds=ttl_seconds,
                    now=now,
                    week_start_day=exec_ctx.week_start_day,
                ):
                    managed_output = cached_entry.get("raw_output")
                    managed_model_alias = exec_ctx.model_alias
                    cache_hit_scope = "persistent"
                    cached_hash = hash_output(managed_output)
                    logger.set_sinks(["validation"]).info(
                        "Context cache hit (persistent)",
                        data={
                            "event": "context_cache_hit",
                            "section_name": section.name,
                            "section_key": section_key,
                            "cache_mode": cache_mode,
                            "cache_scope": cache_hit_scope,
                            "created_at": cached_entry.get("created_at"),
                            "output_hash": cached_hash,
                        },
                    )
                    section_cache_entry = {
                        "raw_output": managed_output,
                        "model_alias": managed_model_alias,
                    }
                    exec_ctx.section_cache[section_key] = section_cache_entry
                    exec_ctx.cache_entry["sections"] = exec_ctx.section_cache
                    exec_ctx.cache_store[exec_ctx.run_scope_key] = exec_ctx.cache_entry
                else:
                    cache_reason = "expired"
            elif cached_entry:
                cache_reason = "template_changed"
            else:
                cache_reason = "missing"
            if managed_output is None and cache_reason:
                logger.set_sinks(["validation"]).info(
                    "Context cache miss",
                    data={
                        "event": "context_cache_miss",
                        "section_name": section.name,
                        "section_key": section_key,
                        "cache_mode": cache_mode,
                        "reason": cache_reason,
                    },
                )

    return CacheDecision(
        managed_output=managed_output,
        managed_model_alias=managed_model_alias,
        cache_hit_scope=cache_hit_scope,
        cache_mode=cache_mode,
    )


def route_section_outputs(
    *,
    output_targets: List[Any],
    skip_llm: bool,
    summary_text: str,
    header_value: Optional[str],
    write_mode: Optional[str],
    section_name: str,
    exec_ctx: SectionExecutionContext,
) -> OutputRoutingResult:
    written_buffers: List[str] = []
    written_files: List[str] = []
    if output_targets and not skip_llm:
        for output_target in output_targets:
            if isinstance(output_target, dict) and output_target.get("type") == "context":
                continue
            if isinstance(output_target, dict) and output_target.get("type") == "buffer":
                target = OutputTarget(type="buffer", name=output_target.get("name"))
            elif isinstance(output_target, str):
                target = OutputTarget(type="file", path=output_target)
            else:
                target = None

            if target is None:
                continue

            try:
                write_result = write_output(
                    target=target,
                    content=summary_text,
                    write_mode=write_mode,
                    buffer_store=exec_ctx.run_buffer_store,
                    buffer_store_registry=exec_ctx.buffer_store_registry,
                    vault_path=exec_ctx.vault_path,
                    header=header_value,
                    buffer_scope=output_target.get("scope") if isinstance(output_target, dict) else None,
                    default_scope="run",
                    metadata={
                        "source": "context_manager",
                        "origin_id": exec_ctx.session_id,
                        "origin_name": section_name,
                        "origin_type": "context_section",
                        "run_id": exec_ctx.run_context.run_id,
                        "write_mode": write_mode or "append",
                        "size_chars": len(summary_text),
                    },
                )
                if write_result.get("type") == "buffer":
                    written_buffers.append(write_result.get("name") or "")
                    logger.info(
                        "Context output written to buffer",
                        data={
                            "session_id": exec_ctx.session_id,
                            "vault_name": exec_ctx.vault_name,
                            "section_name": section_name,
                            "variable": write_result.get("name"),
                            "output_length": len(summary_text),
                        },
                    )
                elif write_result.get("type") == "file":
                    written_files.append(write_result.get("path") or "")
                    logger.info(
                        "Context output written to file",
                        data={
                            "session_id": exec_ctx.session_id,
                            "vault_name": exec_ctx.vault_name,
                            "section_name": section_name,
                            "output_file": write_result.get("path"),
                            "write_mode": write_mode or "append",
                            "output_length": len(summary_text),
                        },
                    )
            except Exception as exc:
                _raise_context_template_error(
                    message=f"Failed to write section output: {exc}",
                    section_name=section_name,
                    phase="output_write",
                    pointer_suffix="@output/@write_mode/@header directives",
                    cause=exc,
                )
    return OutputRoutingResult(
        written_buffers=[name for name in written_buffers if name],
        written_files=[path for path in written_files if path],
    )


async def run_context_section(
    *,
    section: TemplateSection,
    section_index: int,
    messages: List[ModelMessage],
    exec_ctx: SectionExecutionContext,
    manage_context_fn,
) -> SectionExecutionResult:
    section_key = f"{section_index}:{section.name}"
    section_directives = section.directives or {}
    skip_llm = False
    model_directive_value = None
    model_values = section_directives.get("model", [])
    if model_values:
        model_directive_value = model_values[-1]
        if model_directive_value.strip().lower() == "none":
            skip_llm = True

    output_targets = resolve_section_outputs(
        registry=exec_ctx.registry,
        section_directives=section_directives,
        vault_path=exec_ctx.vault_path,
        week_start_day=exec_ctx.week_start_day,
        session_id=exec_ctx.session_id,
        vault_name=exec_ctx.vault_name,
        section_name=section.name,
    )
    emit_context = any(
        isinstance(target, dict) and target.get("type") == "context"
        for target in output_targets
    )
    header_value = resolve_section_header(
        registry=exec_ctx.registry,
        section_directives=section_directives,
        vault_path=exec_ctx.vault_path,
        week_start_day=exec_ctx.week_start_day,
        section_name=section.name,
    )
    write_mode = resolve_section_write_mode(
        registry=exec_ctx.registry,
        section_directives=section_directives,
        vault_path=exec_ctx.vault_path,
        section_name=section.name,
    )

    section_recent_runs = resolve_section_int(
        registry=exec_ctx.registry,
        directive_key="recent_runs",
        section_directives=section_directives,
        vault_path=exec_ctx.vault_path,
        section_name=section.name,
        default=exec_ctx.manager_runs,
    )
    section_recent_summaries = resolve_section_int(
        registry=exec_ctx.registry,
        directive_key="recent_summaries",
        section_directives=section_directives,
        vault_path=exec_ctx.vault_path,
        section_name=section.name,
        default=exec_ctx.recent_summaries_default,
    )
    summaries_limit = None if section_recent_summaries < 0 else section_recent_summaries

    manager_slice = run_slice(messages, section_recent_runs)
    rendered_lines: List[str] = []
    latest_input = ""
    for m in manager_slice:
        role, text = extract_role_and_text(m)
        if text:
            rendered_lines.append(f"{role.capitalize()}: {text}")
        if role.lower() == "user" and text:
            latest_input = text

    rendered_history = "\n".join(rendered_lines)

    summary_messages: List[ModelMessage] = []
    persisted_sections: List[Dict[str, str]] = []

    input_resolution = resolve_section_inputs(
        registry=exec_ctx.registry,
        section=section,
        vault_path=exec_ctx.vault_path,
        week_start_day=exec_ctx.week_start_day,
        run_buffer_store=exec_ctx.run_buffer_store,
        buffer_store_registry=exec_ctx.buffer_store_registry,
        session_id=exec_ctx.session_id,
        vault_name=exec_ctx.vault_name,
        section_key=section_key,
        section_name=section.name,
        model_alias=model_directive_value or exec_ctx.model_alias,
    )
    if input_resolution.skip_required:
        return SectionExecutionResult(summary_messages=[], persisted_sections=[])

    cache_config = resolve_section_cache_config(
        registry=exec_ctx.registry,
        section_directives=section_directives,
        vault_path=exec_ctx.vault_path,
        section_name=section.name,
    )
    cache_decision = resolve_cache_decision(
        section=section,
        section_key=section_key,
        skip_llm=skip_llm,
        cache_config=cache_config,
        exec_ctx=exec_ctx,
    )
    managed_output = cache_decision.managed_output
    managed_model_alias = cache_decision.managed_model_alias
    cache_hit_scope = cache_decision.cache_hit_scope
    cache_mode = cache_decision.cache_mode

    if managed_output is None:
        if skip_llm:
            managed_output = ""
            managed_model_alias = "none"
            logger.set_sinks(["validation"]).info(
                "Context manager LLM skipped (@model none)",
                data={
                    "event": "context_llm_skipped",
                    "section_name": section.name,
                    "section_key": section_key,
                },
            )
        else:
            previous_summary_text = None
            if summaries_limit is None or summaries_limit > 0:
                try:
                    recent_summaries_rows = get_recent_summaries(
                        session_id=exec_ctx.session_id,
                        vault_name=exec_ctx.vault_name,
                        limit=summaries_limit,
                    )
                    logger.set_sinks(["validation"]).info(
                        "Context recent summaries loaded",
                        data={
                            "event": "context_recent_summaries_loaded",
                            "section_name": section.name,
                            "section_key": section_key,
                            "count": len(recent_summaries_rows or []),
                            "limit": summaries_limit,
                        },
                    )
                    if recent_summaries_rows:
                        previous_summary_text = "\n\n".join(
                            [
                                row.get("raw_output") or ""
                                for row in reversed(recent_summaries_rows)
                                if row.get("raw_output")
                            ]
                        ).strip() or None
                except Exception:
                    previous_summary_text = None
                    logger.warning(
                        "Failed to load recent context summaries",
                        metadata={
                            "section_name": section.name,
                            "template_pointer": f"## {section.name} (@recent_summaries directive)",
                            "phase": "summary_fetch",
                        },
                    )

            tools_for_manager, tool_instructions = resolve_section_tools(
                section_directives=section_directives,
                vault_path=exec_ctx.vault_path,
                section_name=section.name,
            )

            manager_input = ContextManagerInput(
                model_alias=exec_ctx.model_alias,
                template=exec_ctx.template,
                template_section=section,
                    context_payload={
                        "latest_input": latest_input,
                        "rendered_history": rendered_history,
                        "previous_summary": previous_summary_text,
                        "input_files": format_input_files_for_prompt(
                            input_resolution.input_file_data,
                            has_empty_directive=(
                                input_resolution.empty_input_file_directive
                                and not input_resolution.input_file_data
                            ),
                        ),
                        "input_files_prompt": input_resolution.input_files_prompt,
                    },
                )
            manager_instruction = CONTEXT_MANAGER_SYSTEM_INSTRUCTION
            if tool_instructions:
                manager_instruction = f"{manager_instruction}\n\n{tool_instructions}"
            logger.set_sinks(["validation"]).info(
                "Context manager LLM invoked",
                data={
                    "event": "context_llm_invoked",
                    "section_name": section.name,
                    "section_key": section_key,
                    "model_alias": model_directive_value or exec_ctx.model_alias,
                    "cache_mode": cache_mode,
                },
            )
            try:
                managed_obj: ContextManagerResult = await manage_context_fn(
                    manager_input,
                    instructions_override=manager_instruction,
                    tools=tools_for_manager,
                    model_override=model_directive_value,
                    deps=ContextManagerDeps(
                        buffer_store=exec_ctx.run_buffer_store,
                        buffer_store_registry=exec_ctx.buffer_store_registry,
                    ),
                )
            except Exception as exc:
                _raise_context_template_error(
                    message=f"Context manager run failed: {exc}",
                    section_name=section.name,
                    phase="manager_run",
                    pointer_suffix="section content and @model/@tools directives",
                    cause=exc,
                )
            managed_output = managed_obj.raw_output
            managed_model_alias = managed_obj.model_alias
            section_cache_entry = {
                "raw_output": managed_output,
                "model_alias": managed_model_alias,
            }
            if exec_ctx.cache_enabled:
                exec_ctx.section_cache[section_key] = section_cache_entry
                exec_ctx.cache_entry["sections"] = exec_ctx.section_cache
                exec_ctx.cache_store[exec_ctx.run_scope_key] = exec_ctx.cache_entry
                if cache_config:
                    cache_mode = cache_config.get("mode")
                    ttl_seconds = cache_config.get("ttl_seconds")
                    if cache_mode:
                        upsert_cached_step_output(
                            run_id=exec_ctx.run_scope_key,
                            session_id=exec_ctx.session_id,
                            vault_name=exec_ctx.vault_name,
                            template_name=exec_ctx.template.name,
                            template_hash=exec_ctx.template.sha256,
                            section_key=section_key,
                            cache_mode=cache_mode,
                            ttl_seconds=ttl_seconds,
                            raw_output=managed_output or "",
                        )

    summary_text = managed_output or "N/A"
    if skip_llm and managed_output == "":
        summary_text = ""
    output_routing = route_section_outputs(
        output_targets=output_targets,
        skip_llm=skip_llm,
        summary_text=summary_text,
        header_value=header_value,
        write_mode=write_mode,
        section_name=section.name,
        exec_ctx=exec_ctx,
    )
    output_hash = hash_output(summary_text)
    logger.set_sinks(["validation"]).info(
        "Context section completed",
        data={
            "event": "context_section_completed",
            "section_name": section.name,
            "section_key": section_key,
            "model_alias": managed_model_alias,
            "output_length": len(summary_text),
            "output_hash": output_hash,
            "from_cache": cache_hit_scope is not None,
            "cache_scope": cache_hit_scope,
            "cache_mode": cache_mode,
        },
    )
    if input_resolution.context_input_outputs:
        section_name = section.name or "Template"
        combined = "\n\n".join([c for c in input_resolution.context_input_outputs if c])
        if combined:
            summary_messages.append(
                ModelRequest(parts=[SystemPromptPart(content=combined)])
            )
            persisted_sections.append(
                {
                    "name": section_name,
                    "output": combined,
                }
            )
    if not skip_llm and emit_context:
        section_name = section.name or "Template"
        summary_title = header_value or section_name
        summary_messages.append(
            ModelRequest(parts=[SystemPromptPart(content=f"{summary_title}:\n{summary_text}")])
        )
        persisted_sections.append(
            {
                "name": section_name,
                "output": summary_text,
            }
        )

    return SectionExecutionResult(
        summary_messages=summary_messages,
        persisted_sections=persisted_sections,
        output_routing=output_routing,
    )
