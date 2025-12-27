from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic_ai import RunContext
from core.directives.model import ModelDirective
from core.llm.agents import create_agent
from core.context.templates import TemplateRecord
from core.context.templates import load_template
from core.logger import UnifiedLogger
from core.constants import CONTEXT_MANAGER_PROMPT, CONTEXT_MANAGER_SYSTEM_INSTRUCTION
from core.directives.bootstrap import ensure_builtin_directives_registered
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
from core.context.store import add_context_summary, upsert_session, get_recent_summaries
from core.settings.store import get_general_settings

logger = UnifiedLogger(tag="context-manager")


@dataclass
class ContextManagerInput:
    """Minimal inputs needed to manage/curate a working context."""

    model_alias: str
    template: TemplateRecord
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
    latest_input = input_data.context_payload.get("latest_input") if isinstance(input_data.context_payload, dict) else None
    rendered_history = input_data.context_payload.get("rendered_history") if isinstance(input_data.context_payload, dict) else None
    previous_summary = input_data.context_payload.get("previous_summary") if isinstance(input_data.context_payload, dict) else None
    input_files = input_data.context_payload.get("input_files") if isinstance(input_data.context_payload, dict) else None
    prompt_parts: List[str] = []
    manager_task = input_data.template.instructions or CONTEXT_MANAGER_PROMPT
    prompt_parts.append(
        "\n".join(
            [
                "=== BEGIN CONTEXT_MANAGER_TASK ===",
                manager_task,
                "=== END CONTEXT_MANAGER_TASK ===",
            ]
        )
    )
    base_template = (input_data.template.template_body or input_data.template.content or "").strip()
    if base_template:
        prompt_parts.append(
            "\n".join(
                [
                    "=== BEGIN EXTRACTION_TEMPLATE ===",
                    base_template,
                    "=== END EXTRACTION_TEMPLATE ===",
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
    passthrough_runs: int = 0,
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

    def _get_latest_directive_value(name: str) -> Optional[str]:
        values = template_directives.get(name, [])
        return values[-1] if values else None

    def _resolve_int_setting(setting_key: str, directive_key: str, default: int = 0) -> int:
        directive_value = _get_latest_directive_value(directive_key)
        if directive_value is not None:
            try:
                result = registry.process_directive(directive_key, directive_value, vault_path)
                return int(result.processed_value)
            except Exception as exc:
                logger.warning(
                    "Failed to process context manager directive; falling back to settings",
                    metadata={"directive": directive_key, "error": str(exc)},
                )

        try:
            entry = get_general_settings().get(setting_key)
            value = entry.value if entry is not None else default
            if value == "" or value is None:
                return 0
            return int(value)
        except Exception:
            return default

    manager_runs = _resolve_int_setting(
        "context_manager_recent_runs",
        "recent-runs",
        manager_runs,
    )
    passthrough_runs = _resolve_int_setting(
        "context_manager_passthrough_runs",
        "passthrough-runs",
        passthrough_runs,
    )
    token_threshold = _resolve_int_setting(
        "context_manager_token_threshold",
        "token-threshold",
        0,
    )
    recent_summaries = _resolve_int_setting(
        "context_manager_recent_summaries",
        "recent-summaries",
        1,
    )

    tools_directive_value = _get_latest_directive_value("tools")
    model_directive_value = _get_latest_directive_value("model")
    input_file_values = template_directives.get("input-file", [])
    empty_input_file_directive = _has_empty_input_file_directive(
        template.template_body or template.content or ""
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
                    return []  # Explicit disable
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

        manager_slice = _run_slice(messages, manager_runs)
        passthrough_slice = _run_slice(messages, passthrough_runs)

        # If both manager and passthrough are explicitly disabled, fall back to raw history (regular chat).
        if manager_runs == 0 and passthrough_runs == 0:
            return list(messages)

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
                rendered_parts: List[str] = []
                for part in parts:
                    if isinstance(part, (UserPromptPart, TextPart)):
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
                    return role, "\n".join(rendered_parts)

            # Try direct content if no parts were rendered
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content:
                return role, content

            return role, ""

        rendered_lines: List[str] = []
        latest_input = ""
        for m in manager_slice:
            role, text = _extract_role_and_text(m)
            if text:
                rendered_lines.append(f"{role.capitalize()}: {text}")
            if role.lower() == "user" and text:
                latest_input = text

        rendered_history = "\n".join(rendered_lines)

        # Estimate token count of the candidate slice (rendered history + latest input); if below threshold, skip management.
        if token_threshold > 0:
            # Estimate size of the full raw history (SessionManager messages) to decide whether to manage.
            estimate_parts: List[str] = []
            for m in messages:
                role, text = _extract_role_and_text(m)
                if text:
                    estimate_parts.append(f"{role}: {text}")
            estimate_basis = "\n".join(estimate_parts)
            token_estimate = estimate_basis and estimate_token_count(estimate_basis) or 0
            logger.debug(
                "Context manager threshold check",
                metadata={
                    "run_id": run_context.run_id,
                    "token_estimate": token_estimate,
                    "threshold": token_threshold,
                    "manager_runs": manager_runs,
                    "passthrough_runs": passthrough_runs,
                },
            )
            if token_estimate < token_threshold:
                # Skip management entirely for this turn; no summary injection, just passthrough slice (or raw history).
                return passthrough_slice or list(messages)
        cache_store = getattr(run_context.deps, "context_manager_cache", None)
        if cache_store is None:
            cache_store = {}
            try:
                setattr(run_context.deps, "context_manager_cache", cache_store)
            except Exception:
                cache_store = {}
        run_scope_key = run_context.run_id or "default_run"
        cache_entry = cache_store.get(run_scope_key, {})

        summary_message: Optional[ModelMessage] = None

        try:
            managed_output: Optional[str] = cache_entry.get("raw_output")
            managed_model_alias: str = cache_entry.get("model_alias", model_alias)

            if managed_output is None:
                input_file_data = None
                if input_file_values:
                    processed_values: List[Any] = []
                    for value in input_file_values:
                        try:
                            result = registry.process_directive(
                                "input-file",
                                value,
                                vault_path,
                                reference_date=datetime.now(),
                                week_start_day=0,
                                state_manager=None,
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
                        processed_values.append(result.processed_value)
                    if processed_values:
                        input_file_data = processed_values[0] if len(processed_values) == 1 else processed_values

                previous_summary_text = None
                if recent_summaries > 0:
                    try:
                        recent_summaries_rows = get_recent_summaries(
                            session_id=session_id,
                            vault_name=vault_name,
                            limit=recent_summaries,
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
                managed_obj = await manage_context(
                    manager_input,
                    instructions_override=manager_instruction,
                    tools=tools_for_manager,
                    model_override=model_directive_value,
                )
                managed_output = managed_obj.raw_output
                managed_model_alias = managed_obj.model_alias
                cache_entry = {
                    "raw_output": managed_output,
                    "model_alias": managed_model_alias,
                    "persisted": False,
                }
                cache_store[run_scope_key] = cache_entry

            # Persist the managed view for observability.
            if cache_entry and not cache_entry.get("persisted"):
                try:
                    upsert_session(session_id=session_id, vault_name=vault_name, metadata=None)
                    add_context_summary(
                        session_id=session_id,
                        vault_name=vault_name,
                        turn_index=None,
                        template=template,
                        model_alias=managed_model_alias,
                        raw_output=managed_output,
                        budget_used=None,
                        sections_included=None,
                        compiled_prompt=None,
                        input_payload={"latest_input": latest_input},
                    )
                    cache_entry["persisted"] = True
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to persist managed context summary", metadata={"error": str(exc)})

            summary_text = managed_output or "N/A"
            summary_message = ModelRequest(parts=[SystemPromptPart(content=f"Context summary (managed):\n{summary_text}")])
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Context management failed in history processor", metadata={"error": str(exc)})
            return list(messages)

        curated_history: List[ModelMessage] = []
        if summary_message:
            curated_history.append(summary_message)
        curated_history.extend(passthrough_slice)
        return curated_history

    return processor
