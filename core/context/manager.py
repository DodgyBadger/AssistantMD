from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic_ai import RunContext
from core.directives.model import ModelDirective
from core.llm.agents import create_agent
from core.context.templates import TemplateRecord, TemplateSection, load_template
from core.logger import UnifiedLogger
from core.constants import (
    CONTEXT_MANAGER_SYSTEM_INSTRUCTION,
    VALID_WEEK_DAYS,
)
from core.directives.bootstrap import ensure_builtin_directives_registered
from core.directives.context_manager import _parse_passthrough_runs
from core.directives.registry import get_global_registry
from core.directives.tools import ToolsDirective
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
from core.tools.utils import estimate_token_count
from core.context.store import (
    add_context_summary,
    get_cached_step_output,
    get_recent_summaries,
    upsert_cached_step_output,
    upsert_session,
)
from core.utils.hash import hash_file_content
from core.runtime.state import has_runtime_context, get_runtime_context

logger = UnifiedLogger(tag="context-manager")


@dataclass
class ContextManagerInput:
    """Minimal inputs needed to manage/curate a working context."""

    model_alias: str
    template: TemplateRecord
    template_section: Optional[TemplateSection]
    context_payload: Dict[str, Any]


@dataclass
class ContextManagerResult:
    """Result of a context management run."""

    raw_output: str
    template: TemplateRecord
    model_alias: str


def _normalize_input_file_lists(input_file_data: Any) -> List[List[Dict[str, Any]]]:
    if not input_file_data:
        return []
    if isinstance(input_file_data, list) and input_file_data and isinstance(input_file_data[0], dict):
        return [input_file_data]
    if isinstance(input_file_data, list):
        return input_file_data
    return []


def _count_input_files(input_file_data: Any) -> Dict[str, int]:
    file_lists = _normalize_input_file_lists(input_file_data)
    if not file_lists:
        return {"total": 0, "paths_only": 0, "missing": 0}
    total = 0
    paths_only = 0
    missing = 0
    for file_list in file_lists:
        for file_data in file_list:
            if not isinstance(file_data, dict):
                continue
            total += 1
            if file_data.get("paths_only"):
                paths_only += 1
            if file_data.get("found") is False:
                missing += 1
    return {"total": total, "paths_only": paths_only, "missing": missing}


def _summarize_input_files(input_file_data: Any, preview_limit: int = 200) -> List[Dict[str, Any]]:
    file_lists = _normalize_input_file_lists(input_file_data)
    if not file_lists:
        return []
    summaries: List[Dict[str, Any]] = []
    for file_list in file_lists:
        for file_data in file_list:
            if not isinstance(file_data, dict):
                continue
            content = ""
            if file_data.get("found") and not file_data.get("paths_only"):
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
                    "paths_only": file_data.get("paths_only", False),
                    "content_length": len(content),
                    "content_preview": preview,
                }
            )
    return summaries


def _hash_output(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hash_file_content(value, length=12)


def _resolve_cache_now(run_context: RunContext[Any]) -> datetime:
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


def _format_input_files_for_prompt(
    input_file_data: Any,
    has_empty_directive: bool = False,
) -> Optional[str]:
    file_lists = _normalize_input_file_lists(input_file_data)
    if not file_lists and not has_empty_directive:
        return None

    flattened_files: List[Dict[str, Any]] = []
    for file_list in file_lists:
        flattened_files.extend(file_list)

    formatted_content: List[str] = []
    path_only_entries: List[str] = []
    for file_data in flattened_files:
        if not isinstance(file_data, dict):
            continue
        if file_data.get("paths_only"):
            label = f"- {file_data.get('filepath', 'unknown')}"
            if not file_data.get("found", True):
                error_msg = file_data.get("error", "File not found")
                label += f" (missing: {error_msg})"
            path_only_entries.append(label)
        elif file_data.get("found") and file_data.get("content"):
            formatted_content.append(
                f"--- FILE: {file_data.get('filepath', 'unknown')} ---\n{file_data.get('content', '')}"
            )
        elif file_data.get("found") is False:
            formatted_content.append(
                f"--- FILE: {file_data.get('filepath', 'unknown')} ---\n[FILE NOT FOUND: {file_data.get('error')}]"
            )

    if not path_only_entries and not formatted_content:
        if has_empty_directive:
            return "\n".join(
                [
                    "=== BEGIN INPUT_FILES ===",
                    "--- FILE PATHS (CONTENT NOT INLINED) ---",
                    "[NO INPUT FILES SPECIFIED IN TEMPLATE]",
                    "=== END INPUT_FILES ===",
                ]
            )
        return None

    sections: List[str] = []
    sections.append("=== BEGIN INPUT_FILES ===")
    if path_only_entries:
        sections.append("--- FILE PATHS (CONTENT NOT INLINED) ---")
        sections.append("\n".join(path_only_entries))
    if formatted_content:
        sections.append("\n\n".join(formatted_content))
    sections.append("=== END INPUT_FILES ===")

    return "\n".join(sections)


def _has_empty_input_file_directive(content: str) -> bool:
    if not content:
        return False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("@input-file"):
            return stripped in ("@input-file", "@input-file:")
    return False


def _resolve_week_start_day(frontmatter: Optional[Dict[str, Any]]) -> int:
    """
    Resolve week_start_day from template frontmatter.

    Returns 0=Monday .. 6=Sunday, defaulting to Monday on missing/invalid values.
    """
    if not frontmatter:
        return 0
    raw_value = frontmatter.get("week_start_day")
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


def _parse_db_timestamp(raw_value: Optional[str]) -> Optional[datetime]:
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


def _generate_numbered_file_path(full_file_path: str, vault_path: str) -> str:
    """Generate a numbered file path for write-mode new."""
    if full_file_path.startswith(vault_path + '/'):
        relative_path = full_file_path[len(vault_path) + 1:]
    else:
        relative_path = full_file_path

    if relative_path.endswith('.md'):
        base_path = relative_path[:-3]
    else:
        base_path = relative_path

    directory = os.path.dirname(base_path) if os.path.dirname(base_path) else '.'
    basename = os.path.basename(base_path)
    full_directory = os.path.join(vault_path, directory)

    existing_numbers = set()
    if os.path.exists(full_directory):
        for filename in os.listdir(full_directory):
            if filename.startswith(f"{basename}_") and filename.endswith('.md'):
                number_part = filename[len(basename) + 1:-3]
                try:
                    number = int(number_part)
                    existing_numbers.add(number)
                except ValueError:
                    continue

    next_number = 0
    while next_number in existing_numbers:
        next_number += 1

    numbered_relative_path = f"{base_path}_{next_number:03d}.md"
    return f"{vault_path}/{numbered_relative_path}"


def _start_of_week(value: datetime, week_start_day: int) -> datetime:
    delta_days = (value.weekday() - week_start_day) % 7
    return (value - timedelta(days=delta_days)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _cache_entry_is_valid(
    *,
    created_at: Optional[str],
    cache_mode: str,
    ttl_seconds: Optional[int],
    now: datetime,
    week_start_day: int,
) -> bool:
    created_dt = _parse_db_timestamp(created_at)
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
        return _start_of_week(created_dt, week_start_day) == _start_of_week(now, week_start_day)
    if cache_mode == "session":
        return True
    return False


def _resolve_passthrough_runs(frontmatter: Optional[Dict[str, Any]], default: int) -> int:
    if not frontmatter:
        return default
    raw_value = frontmatter.get("passthrough_runs")
    if raw_value is None:
        raw_value = frontmatter.get("passthrough-runs")
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


def _resolve_token_threshold(frontmatter: Optional[Dict[str, Any]], default: int) -> int:
    if not frontmatter:
        return default
    raw_value = frontmatter.get("token_threshold")
    if raw_value is None:
        raw_value = frontmatter.get("token-threshold")
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


async def manage_context(
    input_data: ContextManagerInput,
    instructions_override: Optional[str] = None,
    tools: Optional[List[Any]] = None,
    model_override: Optional[str] = None,
) -> ContextManagerResult:
    """
    Manage a concise working context using the provided template and model.

    Patterns:
    - Minimal manager instruction added via agent.instructions (no system_prompt)
    - Manager prompt + template content + rendered history + latest input become the user prompt
    - No message_history passed to the manager agent (stateless per call)
    - Returns natural language output
    """
    # Resolve model instance
    model_directive = ModelDirective()
    model_to_use = model_override or input_data.model_alias
    model_instance = model_directive.process_value(model_to_use, "context-manager")

    manager_instruction = instructions_override if instructions_override is not None else CONTEXT_MANAGER_SYSTEM_INSTRUCTION
    context_instructions = input_data.template.instructions
    latest_input = input_data.context_payload.get("latest_input") if isinstance(input_data.context_payload, dict) else None
    rendered_history = input_data.context_payload.get("rendered_history") if isinstance(input_data.context_payload, dict) else None
    previous_summary = input_data.context_payload.get("previous_summary") if isinstance(input_data.context_payload, dict) else None
    input_files = input_data.context_payload.get("input_files") if isinstance(input_data.context_payload, dict) else None
    prompt_parts: List[str] = []
    manager_task = ""
    section_body = None
    if input_data.template_section is not None:
        section_body = input_data.template_section.cleaned_content
    manager_task = (section_body or input_data.template.template_body or input_data.template.content or "").strip()
    if manager_task:
        prompt_parts.append(
            "\n".join(
                [
                    "=== BEGIN CONTEXT_MANAGER_TASK ===",
                    manager_task,
                    "=== END CONTEXT_MANAGER_TASK ===",
                ]
            )
        )
    if input_files:
        prompt_parts.append(input_files)
    if previous_summary:
        prompt_parts.append(
            "\n".join(
                [
                    "=== BEGIN PRIOR_SUMMARY ===",
                    previous_summary,
                    "=== END PRIOR_SUMMARY ===",
                ]
            )
        )
    if rendered_history:
        prompt_parts.append(
            "\n".join(
                [
                    "=== BEGIN RECENT_CONVERSATION ===",
                    rendered_history,
                    "=== END RECENT_CONVERSATION ===",
                ]
            )
        )
    if latest_input:
        prompt_parts.append(
            "\n".join(
                [
                    "=== BEGIN LATEST_USER_INPUT ===",
                    latest_input,
                    "=== END LATEST_USER_INPUT ===",
                ]
            )
        )
    prompt = "\n\n".join(prompt_parts).strip() or "No content provided."

    agent = await create_agent(
        model=model_instance,
        tools=tools,
    )
    agent.instructions(lambda _ctx, text=manager_instruction: text)
    if context_instructions:
        agent.instructions(lambda _ctx, text=context_instructions: text)
    result = await agent.run(prompt)
    result_output = getattr(result, "output", None)

    raw_output = str(result_output)

    return ContextManagerResult(
        raw_output=raw_output,
        template=input_data.template,
        model_alias=model_to_use,
    )


def build_context_manager_history_processor(
    *,
    session_id: str,
    vault_name: str,
    vault_path: str,
    model_alias: str,
    template_name: str,
    manager_runs: int = 0,
    passthrough_runs: int = -1,
)-> Callable[[RunContext[Any], List[ModelMessage]], Awaitable[List[ModelMessage]]]:
    """
    Factory for a history processor that manages a curated view and injects it
    as a system message ahead of the recent turns. If management fails, the
    original history is returned unchanged.
    """

    ensure_builtin_directives_registered()
    registry = get_global_registry()
    template = load_template(template_name, Path(vault_path))
    template_directives = template.directives or {}
    template_sections = template.template_sections or []
    week_start_day = _resolve_week_start_day(template.frontmatter)
    chat_instructions = (template.chat_instructions or "").strip() or None
    passthrough_runs = _resolve_passthrough_runs(template.frontmatter, passthrough_runs)
    chat_instruction_message: Optional[ModelMessage] = None
    if chat_instructions:
        chat_instruction_message = ModelRequest(
            parts=[SystemPromptPart(content=chat_instructions)]
        )

    token_threshold = 0
    recent_summaries = 0
    template_token_threshold = _resolve_token_threshold(template.frontmatter, token_threshold)
    if template_sections:
        default_sections = template_sections
    elif template.template_body or template.content:
        default_sections = [
            TemplateSection(
                name=template.template_section or "Template",
                content=template.template_body or template.content or "",
                cleaned_content=template.template_body or template.content or "",
                directives=template_directives,
            )
        ]
    else:
        default_sections = []

    logger.info(
        "Context template loaded",
        data={
            "template_name": template.name,
            "template_source": template.source,
            "section_count": len(default_sections),
            "passthrough_runs": passthrough_runs,
        },
    )
    logger.set_sinks(["validation"]).info(
        "Context template loaded",
        data={
            "event": "context_template_loaded",
            "template_name": template.name,
            "template_source": template.source,
            "section_count": len(default_sections),
            "passthrough_runs": passthrough_runs,
        },
    )

    async def processor(run_context: RunContext[Any], messages: List[ModelMessage]) -> List[ModelMessage]:
        if not messages:
            return []

        def _run_slice(msgs: List[ModelMessage], runs_to_take: int) -> List[ModelMessage]:
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

        def _find_last_user_idx(msgs: List[ModelMessage]) -> Optional[int]:
            for idx in range(len(msgs) - 1, -1, -1):
                m = msgs[idx]
                role = getattr(m, "role", None)
                if role and role.lower() == "user":
                    return idx
                if isinstance(m, ModelRequest):
                    return idx
            return None

        last_user_idx = _find_last_user_idx(messages)
        latest_user_message = messages[last_user_idx] if last_user_idx is not None else None
        history_before_latest = messages[:last_user_idx] if last_user_idx is not None else messages
        passthrough_slice = _run_slice(history_before_latest, passthrough_runs)

        if not default_sections:
            curated_history: List[ModelMessage] = []
            if chat_instruction_message:
                curated_history.append(chat_instruction_message)
            curated_history.extend(passthrough_slice)
            if latest_user_message is not None:
                curated_history.append(latest_user_message)
            return curated_history

        # Render the recent slice into a simple text transcript.
        def _extract_role_and_text(msg: ModelMessage) -> tuple[str, str]:
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
                    else:
                        part_content = getattr(part, "content", None)
                        if isinstance(part_content, str):
                            rendered_parts.append(part_content)
                if rendered_parts:
                    if has_system_part and role == "user":
                        return "system", "\n".join(rendered_parts)
                    return role, "\n".join(rendered_parts)

            # Try direct content if no parts were rendered
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content:
                return role, content

            return role, ""

        token_estimate = None
        cache_store = getattr(run_context.deps, "context_manager_cache", None)
        cache_enabled = bool(run_context.run_id)
        if cache_enabled:
            if cache_store is None:
                cache_store = {}
                try:
                    setattr(run_context.deps, "context_manager_cache", cache_store)
                except Exception:
                    cache_store = {}
            run_scope_key = run_context.run_id
            cache_entry = cache_store.get(run_scope_key, {})
            section_cache = cache_entry.get("sections", {})
        else:
            logger.warning(
                "Context manager cache disabled due to missing run_id",
                metadata={"session_id": session_id, "vault_name": vault_name},
            )
            run_scope_key = None
            cache_entry = {}
            section_cache = {}

        summary_messages: List[ModelMessage] = []
        persisted_sections: List[Dict[str, Any]] = []

        if template_token_threshold > 0:
            estimate_parts: List[str] = []
            for m in messages:
                role, text = _extract_role_and_text(m)
                if text:
                    estimate_parts.append(f"{role}: {text}")
            estimate_basis = "\n".join(estimate_parts)
            token_estimate = estimate_basis and estimate_token_count(estimate_basis) or 0
            logger.debug(
                "Context manager template threshold check",
                metadata={
                    "run_id": run_context.run_id,
                    "token_estimate": token_estimate,
                    "threshold": template_token_threshold,
                },
            )
            if token_estimate < template_token_threshold:
                logger.set_sinks(["validation"]).info(
                    "Context template skipped (token threshold)",
                    data={
                        "event": "context_template_skipped",
                        "template_name": template.name,
                        "token_estimate": token_estimate,
                        "threshold": template_token_threshold,
                    },
                )
                passthrough_slice = _run_slice(history_before_latest, -1)
                curated_history: List[ModelMessage] = []
                if chat_instruction_message:
                    curated_history.append(chat_instruction_message)
                curated_history.extend(passthrough_slice)
                if latest_user_message is not None:
                    curated_history.append(latest_user_message)
                return curated_history

        buffer_store = getattr(run_context.deps, "buffer_store", None)
        for idx, section in enumerate(default_sections):
            section_key = f"{idx}:{section.name}"
            section_directives = section.directives or {}
            output_target = None
            output_values = section_directives.get("output-file", [])
            if output_values:
                try:
                    output_result = registry.process_directive(
                        "output-file",
                        output_values[-1],
                        vault_path,
                        reference_date=datetime.now(),
                        week_start_day=week_start_day,
                    )
                    if output_result.success:
                        output_target = output_result.processed_value
                        if isinstance(output_target, dict) and output_target.get("type") == "buffer":
                            logger.info(
                                "Context output target resolved (buffer)",
                                data={
                                    "session_id": session_id,
                                    "vault_name": vault_name,
                                    "section_name": section.name,
                                    "variable": output_target.get("name"),
                                },
                            )
                        elif isinstance(output_target, str):
                            logger.info(
                                "Context output target resolved (file)",
                                data={
                                    "session_id": session_id,
                                    "vault_name": vault_name,
                                    "section_name": section.name,
                                    "output_file": output_target,
                                },
                            )
                except Exception as exc:
                    logger.warning(
                        "Failed to process context manager output-file directive",
                        metadata={"error": str(exc)},
                    )
            header_value = None
            header_values = section_directives.get("header", [])
            if header_values:
                try:
                    header_result = registry.process_directive(
                        "header",
                        header_values[-1],
                        vault_path,
                        reference_date=datetime.now(),
                        week_start_day=week_start_day,
                    )
                    if header_result.success:
                        header_value = header_result.processed_value
                except Exception as exc:
                    logger.warning(
                        "Failed to process context manager header directive",
                        metadata={"error": str(exc)},
                    )
            write_mode = None
            write_mode_values = section_directives.get("write-mode", [])
            if write_mode_values:
                try:
                    write_mode_result = registry.process_directive(
                        "write-mode",
                        write_mode_values[-1],
                        vault_path,
                    )
                    if write_mode_result.success:
                        write_mode = write_mode_result.processed_value
                except Exception as exc:
                    logger.warning(
                        "Failed to process context manager write-mode directive",
                        metadata={"error": str(exc)},
                    )

            def _resolve_section_int(directive_key: str, default: int = 0) -> int:
                values = section_directives.get(directive_key, [])
                if values:
                    try:
                        result = registry.process_directive(
                            directive_key,
                            values[-1],
                            vault_path,
                        )
                        return int(result.processed_value)
                    except Exception as exc:
                        logger.warning(
                            "Failed to process context manager directive; falling back to defaults",
                            metadata={"directive": directive_key, "error": str(exc)},
                        )
                return default

            section_recent_runs = _resolve_section_int("recent-runs", manager_runs)
            section_recent_summaries = _resolve_section_int("recent-summaries", recent_summaries)
            summaries_limit = None if section_recent_summaries < 0 else section_recent_summaries

            manager_slice = _run_slice(messages, section_recent_runs)
            rendered_lines: List[str] = []
            latest_input = ""
            for m in manager_slice:
                role, text = _extract_role_and_text(m)
                if text:
                    rendered_lines.append(f"{role.capitalize()}: {text}")
                if role.lower() == "user" and text:
                    latest_input = text

            rendered_history = "\n".join(rendered_lines)

            try:
                managed_output: Optional[str] = None
                managed_model_alias: str = model_alias
                section_cache_entry = section_cache.get(section_key, {})
                managed_output = section_cache_entry.get("raw_output")
                managed_model_alias = section_cache_entry.get("model_alias", model_alias)
                cache_hit_scope: Optional[str] = None
                cache_mode: Optional[str] = None
                if cache_enabled and managed_output is not None:
                    cache_hit_scope = "run"
                    cached_hash = _hash_output(managed_output)
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
                elif not cache_enabled:
                    managed_output = None

                input_file_values = section_directives.get("input-file", [])
                empty_input_file_directive = _has_empty_input_file_directive(section.content)
                input_file_data = None
                if input_file_values:
                    processed_values: List[Any] = []
                    for value in input_file_values:
                        try:
                            result = registry.process_directive(
                                "input-file",
                                value,
                                vault_path,
                                # TODO: use centralized time manager once available for consistency with workflows.
                                reference_date=datetime.now(),
                                week_start_day=week_start_day,
                                state_manager=None,
                                buffer_store=buffer_store,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to process context manager input-file directive",
                                metadata={"error": str(exc)},
                            )
                            continue
                        if not result.success:
                            logger.warning(
                                "Context manager input-file directive returned an error",
                                metadata={"error": result.error_message},
                            )
                            continue
                        if isinstance(result.processed_value, list):
                            if any(
                                item.get("_workflow_signal") == "skip_step"
                                for item in result.processed_value
                                if isinstance(item, dict)
                            ):
                                processed_values = []
                                input_file_data = None
                                logger.info(
                                    "Skipping context section due to required input-file directive",
                                    metadata={"section": section.name},
                                )
                                break
                        processed_values.append(result.processed_value)
                    if processed_values:
                        input_file_data = processed_values[0] if len(processed_values) == 1 else processed_values
                    elif input_file_data is None and processed_values == []:
                        logger.set_sinks(["validation"]).info(
                            "Context section skipped (input-file required)",
                            data={
                                "event": "context_section_skipped",
                                "section_name": section.name,
                                "section_key": section_key,
                                "reason": "input_file_required",
                            },
                        )
                        continue

                if input_file_values:
                    counts = _count_input_files(input_file_data)
                    file_summaries = _summarize_input_files(input_file_data)
                    logger.set_sinks(["validation"]).info(
                        "Context input files resolved",
                        data={
                            "event": "context_input_files_resolved",
                            "section_name": section.name,
                            "section_key": section_key,
                            "file_count": counts["total"],
                            "paths_only_count": counts["paths_only"],
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
                                "paths_only_count": counts["paths_only"],
                                "missing_count": counts["missing"],
                                "files": file_summaries,
                            },
                        )

                cache_config: Optional[Dict[str, Any]] = None
                cache_values = section_directives.get("cache", [])
                if cache_values:
                    try:
                        result = registry.process_directive(
                            "cache",
                            cache_values[-1],
                            vault_path,
                        )
                        cache_config = result.processed_value
                    except Exception as exc:
                        logger.warning(
                            "Failed to process context manager cache directive",
                            metadata={"error": str(exc)},
                        )
                if cache_config and not cache_mode:
                    cache_mode = cache_config.get("mode")

                if cache_enabled and managed_output is None and cache_config:
                    ttl_seconds = cache_config.get("ttl_seconds")
                    if cache_mode:
                        cached_entry = get_cached_step_output(
                            session_id=session_id,
                            vault_name=vault_name,
                            template_name=template.name,
                            section_key=section_key,
                            cache_mode=cache_mode,
                        )
                        cache_reason = None
                        if cached_entry and cached_entry.get("template_hash") == template.sha256:
                            now = _resolve_cache_now(run_context)
                            if _cache_entry_is_valid(
                                created_at=cached_entry.get("created_at"),
                                cache_mode=cache_mode,
                                ttl_seconds=ttl_seconds,
                                now=now,
                                week_start_day=week_start_day,
                            ):
                                managed_output = cached_entry.get("raw_output")
                                managed_model_alias = model_alias
                                cache_hit_scope = "persistent"
                                cached_hash = _hash_output(managed_output)
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
                                section_cache[section_key] = section_cache_entry
                                cache_entry["sections"] = section_cache
                                cache_store[run_scope_key] = cache_entry
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

                if managed_output is None:
                    previous_summary_text = None
                    if summaries_limit is None or summaries_limit > 0:
                        try:
                            recent_summaries_rows = get_recent_summaries(
                                session_id=session_id,
                                vault_name=vault_name,
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

                    tools_for_manager = None
                    tool_instructions = ""
                    tools_directive_value = None
                    model_directive_value = None
                    tools_values = section_directives.get("tools", [])
                    if tools_values:
                        tools_directive_value = tools_values[-1]
                    model_values = section_directives.get("model", [])
                    if model_values:
                        model_directive_value = model_values[-1]
                    if tools_directive_value:
                        try:
                            tools_directive = ToolsDirective()
                            tools_for_manager, tool_instructions = tools_directive.process_value(
                                tools_directive_value, vault_path=vault_path
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to process context manager tools directive",
                                metadata={"error": str(exc)},
                            )
                            tools_for_manager = None
                            tool_instructions = ""

                    manager_input = ContextManagerInput(
                        model_alias=model_alias,
                        template=template,
                        template_section=section,
                        context_payload={
                            "latest_input": latest_input,
                            "rendered_history": rendered_history,
                            "previous_summary": previous_summary_text,
                            "input_files": _format_input_files_for_prompt(
                                input_file_data,
                                has_empty_directive=empty_input_file_directive and not input_file_data,
                            ),
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
                            "model_alias": model_directive_value or model_alias,
                            "cache_mode": cache_mode,
                        },
                    )
                    managed_obj = await manage_context(
                        manager_input,
                        instructions_override=manager_instruction,
                        tools=tools_for_manager,
                        model_override=model_directive_value,
                    )
                    managed_output = managed_obj.raw_output
                    managed_model_alias = managed_obj.model_alias
                    section_cache_entry = {
                        "raw_output": managed_output,
                        "model_alias": managed_model_alias,
                    }
                    if cache_enabled:
                        section_cache[section_key] = section_cache_entry
                        cache_entry["sections"] = section_cache
                        cache_store[run_scope_key] = cache_entry
                        if cache_config:
                            cache_mode = cache_config.get("mode")
                            ttl_seconds = cache_config.get("ttl_seconds")
                            if cache_mode:
                                upsert_cached_step_output(
                                    run_id=run_scope_key,
                                    session_id=session_id,
                                    vault_name=vault_name,
                                    template_name=template.name,
                                    template_hash=template.sha256,
                                    section_key=section_key,
                                    cache_mode=cache_mode,
                                    ttl_seconds=ttl_seconds,
                                    raw_output=managed_output or "",
                                )

                summary_text = managed_output or "N/A"
                if output_target:
                    if isinstance(output_target, dict) and output_target.get("type") == "buffer":
                        if buffer_store is not None:
                            if write_mode == "replace":
                                buffer_mode = "replace"
                            else:
                                buffer_mode = "append"
                            buffer_store.put(
                                output_target.get("name", ""),
                                summary_text,
                                mode=buffer_mode,
                                metadata={
                                    "source": "context_manager",
                                    "section": section.name,
                                },
                            )
                            logger.info(
                                "Context output written to buffer",
                                data={
                                    "session_id": session_id,
                                    "vault_name": vault_name,
                                    "section_name": section.name,
                                    "variable": output_target.get("name"),
                                    "output_length": len(summary_text),
                                },
                            )
                    elif isinstance(output_target, str):
                        try:
                            output_file = os.path.join(vault_path, output_target)
                            if write_mode == "new":
                                output_file = _generate_numbered_file_path(output_file, vault_path)
                            os.makedirs(os.path.dirname(output_file), exist_ok=True)
                            if write_mode == "new" or write_mode == "replace":
                                file_mode = "w"
                            else:
                                file_mode = "a"
                            with open(output_file, file_mode, encoding="utf-8") as file:
                                if header_value:
                                    file.write(f"# {header_value}\n\n")
                                file.write(summary_text)
                                file.write("\n\n")
                            logger.info(
                                "Context output written to file",
                                data={
                                    "session_id": session_id,
                                    "vault_name": vault_name,
                                    "section_name": section.name,
                                    "output_file": output_file,
                                    "write_mode": write_mode or "append",
                                    "output_length": len(summary_text),
                                },
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to write context manager output file",
                                metadata={"error": str(exc)},
                            )
                output_hash = _hash_output(summary_text)
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
                section_name = section.name or "Template"
                summary_title = f"Context summary (managed: {section_name})"
                summary_messages.append(
                    ModelRequest(parts=[SystemPromptPart(content=f"{summary_title}:\n{summary_text}")])
                )
                persisted_sections.append(
                    {
                        "name": section_name,
                        "output": summary_text,
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Context management failed in history processor", metadata={"error": str(exc)})
                return list(messages)

        if persisted_sections and not cache_entry.get("persisted"):
            try:
                upsert_session(session_id=session_id, vault_name=vault_name, metadata=None)
                combined_output = "\n\n".join(
                    [
                        f"## {section['name']}\n{section['output']}"
                        for section in persisted_sections
                    ]
                )
                add_context_summary(
                    session_id=session_id,
                    vault_name=vault_name,
                    turn_index=None,
                    template=template,
                    model_alias=model_alias,
                    raw_output=combined_output,
                    budget_used=None,
                    sections_included=None,
                    compiled_prompt=None,
                    input_payload={
                        "sections": [section["name"] for section in persisted_sections],
                    },
                )
                logger.info(
                    "Context summary persisted",
                    data={
                        "session_id": session_id,
                        "vault_name": vault_name,
                        "template_name": template.name,
                        "sections": [section["name"] for section in persisted_sections],
                    },
                )
                logger.set_sinks(["validation"]).info(
                    "Context summary persisted",
                    data={
                        "event": "context_summary_persisted",
                        "session_id": session_id,
                        "vault_name": vault_name,
                        "template_name": template.name,
                        "sections": [section["name"] for section in persisted_sections],
                        "summary_length": len(combined_output),
                    },
                )
                if cache_enabled:
                    cache_entry["persisted"] = True
                    cache_store[run_scope_key] = cache_entry
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to persist managed context summary", metadata={"error": str(exc)})

        curated_history: List[ModelMessage] = []
        if chat_instruction_message:
            curated_history.append(chat_instruction_message)
        curated_history.extend(summary_messages)
        curated_history.extend(passthrough_slice)
        if latest_user_message is not None:
            curated_history.append(latest_user_message)
        summary_sections: List[str] = []
        for msg in summary_messages:
            parts = getattr(msg, "parts", None)
            if not parts:
                continue
            for part in parts:
                if isinstance(part, SystemPromptPart):
                    content = getattr(part, "content", "") or ""
                    if content.startswith("Context summary (managed: "):
                        section = content.split("Context summary (managed: ", 1)[1]
                        section = section.split(")", 1)[0]
                        if section:
                            summary_sections.append(section)
        logger.set_sinks(["validation"]).info(
            "Context history compiled",
            data={
                "event": "context_history_compiled",
                "session_id": session_id,
                "vault_name": vault_name,
                "template_name": template.name,
                "total_messages": len(curated_history),
                "summary_section_count": len(summary_sections),
                "summary_sections": summary_sections,
                "passthrough_count": len(passthrough_slice),
                "latest_user_included": latest_user_message is not None,
            },
        )
        return curated_history

    return processor
