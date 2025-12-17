from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic_ai import RunContext
from core.directives.model import ModelDirective
from core.llm.agents import create_agent
from core.context.templates import TemplateRecord
from core.context.templates import load_template
from core.logger import UnifiedLogger
from core.constants import CONTEXT_MANAGER_PROMPT, CONTEXT_MANAGER_SYSTEM_INSTRUCTION
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
from core.context.store import add_context_summary, upsert_session
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
    prompt_parts: List[str] = []
    prompt_parts.append(f"## Context manager task\n{CONTEXT_MANAGER_PROMPT}")
    base_template = (input_data.template.content or "").strip()
    if base_template:
        prompt_parts.append(f"## Extraction template\n{base_template}")
    if previous_summary:
        prompt_parts.append(f"## Prior summary (persisted)\n{previous_summary}")
    if rendered_history:
        prompt_parts.append(f"## Recent conversation\n{rendered_history}")
    if latest_input:
        prompt_parts.append(f"## Latest user input\n{latest_input}")
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
)-> list[ModelMessage]:
    """
    Factory for a history processor that manages a curated view and injects it
    as a system message ahead of the recent turns. If management fails, the
    original history is returned unchanged.
    """

    template = load_template(template_name, Path(vault_path))

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
        try:
            threshold_entry = get_general_settings().get("context_manager_token_threshold")
            threshold = int(threshold_entry.value) if threshold_entry and threshold_entry.value is not None else 0
        except Exception:
            threshold = 0

        if threshold > 0:
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
                    "threshold": threshold,
                    "manager_runs": manager_runs,
                    "passthrough_runs": passthrough_runs,
                },
            )
            if token_estimate < threshold:
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
                # Pick manager model override if available and valid
                manager_model_alias = None
                try:
                    manager_model_entry = get_general_settings().get("context_manager_model")
                    manager_model_alias = manager_model_entry.value if manager_model_entry else None
                except Exception:
                    manager_model_alias = None

                previous_summary_text = None
                try:
                    recent_summaries = get_recent_summaries(
                        session_id=session_id,
                        vault_name=vault_name,
                        limit=1,
                    )
                    if recent_summaries:
                        prior = recent_summaries[0]
                        previous_summary_text = prior.get("raw_output") or prior.get("summary") or None
                except Exception:
                    previous_summary_text = None

                manager_input = ContextManagerInput(
                    model_alias=model_alias,
                    template=template,
                    context_payload={
                        "latest_input": latest_input,
                        "rendered_history": rendered_history,
                        "previous_summary": previous_summary_text,
                    },
                )
                managed_obj = await manage_context(
                    manager_input,
                    instructions_override=None,
                    tools=None,
                    model_override=manager_model_alias if manager_model_alias else None,
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
                        summary_json=None,
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
