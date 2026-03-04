from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from pydantic_ai import RunContext
from core.directives.model import ModelDirective
from core.llm.agents import create_agent
from core.llm.model_selection import ModelExecutionSpec, resolve_model_execution_spec
from core.context.templates import load_template
from core.logger import UnifiedLogger
from core.constants import (
    CONTEXT_MANAGER_SYSTEM_INSTRUCTION,
    CONTEXT_TEMPLATE_ERROR_HANDOFF_INSTRUCTION,
)
from core.directives.bootstrap import ensure_builtin_directives_registered
from core.directives.registry import get_global_registry
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart, UserContent
from core.tools.utils import estimate_token_count
from core.context.store import add_context_summary, upsert_session
from core.runtime.buffers import BufferStore
from core.context.manager_helpers import (
    extract_role_and_text,
    find_last_user_idx,
    prepare_template_runtime,
    run_context_section,
    run_slice,
)
from core.context.manager_types import (
    ContextTemplateError,
    ContextManagerDeps,
    ContextManagerInput,
    ContextManagerResult,
    SectionExecutionContext,
)

logger = UnifiedLogger(tag="context-manager")
PromptInput = str | Sequence[UserContent]


async def manage_context(
    input_data: ContextManagerInput,
    instructions_override: Optional[str] = None,
    tools: Optional[List[Any]] = None,
    model_override: Optional[str] = None,
    deps: Optional[ContextManagerDeps] = None,
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
    model_execution = resolve_model_execution_spec(model_to_use)
    if model_execution.mode == "skip":
        return ContextManagerResult(
            raw_output="",
            template=input_data.template,
            model_alias="none",
        )
    model_instance = model_directive.process_value(model_to_use, "context-manager")
    if isinstance(model_instance, ModelExecutionSpec) and model_instance.mode == "skip":
        return ContextManagerResult(
            raw_output="",
            template=input_data.template,
            model_alias="none",
        )

    manager_instruction = instructions_override if instructions_override is not None else CONTEXT_MANAGER_SYSTEM_INSTRUCTION
    context_instructions = input_data.template.instructions
    latest_input = input_data.context_payload.get("latest_input") if isinstance(input_data.context_payload, dict) else None
    rendered_history = input_data.context_payload.get("rendered_history") if isinstance(input_data.context_payload, dict) else None
    previous_summary = input_data.context_payload.get("previous_summary") if isinstance(input_data.context_payload, dict) else None
    input_files = input_data.context_payload.get("input_files") if isinstance(input_data.context_payload, dict) else None
    input_files_prompt = (
        input_data.context_payload.get("input_files_prompt")
        if isinstance(input_data.context_payload, dict)
        else None
    )
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
    if input_files and not input_files_prompt:
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
    prompt_text = "\n\n".join(prompt_parts).strip() or "No content provided."
    prompt: PromptInput = prompt_text
    if input_files_prompt:
        if isinstance(input_files_prompt, str):
            prompt = "\n\n".join([prompt_text, input_files_prompt]).strip()
        elif isinstance(input_files_prompt, Sequence):
            multimodal_parts: List[UserContent] = []
            if prompt_text:
                multimodal_parts.append(prompt_text)
            for part in input_files_prompt:
                multimodal_parts.append(part)
            prompt = multimodal_parts

    agent = await create_agent(
        model=model_instance,
        tools=tools,
    )
    agent.instructions(lambda _ctx, text=manager_instruction: text)
    if context_instructions:
        agent.instructions(lambda _ctx, text=context_instructions: text)
    result = await agent.run(prompt, deps=deps)
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
    try:
        template = load_template(template_name, Path(vault_path))
        runtime = prepare_template_runtime(template, passthrough_runs, token_threshold_default=0)
    except Exception as exc:
        template_error = ContextTemplateError(
            f"Failed to load/parse context template '{template_name}': {exc}",
            template_pointer="Template frontmatter and ## section headings",
            section_name=None,
            phase="template_load",
        )
        logger.warning(
            "Context template load failed; falling back to passthrough history",
            metadata={
                "error": str(template_error),
                "phase": template_error.phase,
                "template_pointer": template_error.template_pointer,
            },
        )

        async def processor(_run_context: RunContext[Any], messages: List[ModelMessage]) -> List[ModelMessage]:
            warning = (
                CONTEXT_TEMPLATE_ERROR_HANDOFF_INSTRUCTION
                + 
                f"phase={template_error.phase}; "
                f"template_pointer={template_error.template_pointer}; "
                f"message={template_error}"
            )
            return [ModelRequest(parts=[SystemPromptPart(content=warning)])] + list(messages)

        return processor
    recent_summaries = 0
    default_sections = runtime.sections
    week_start_day = runtime.week_start_day
    passthrough_runs = runtime.passthrough_runs
    chat_instruction_message = runtime.chat_instruction_message
    template_token_threshold = runtime.token_threshold

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

        last_user_idx = find_last_user_idx(messages)
        latest_user_message = messages[last_user_idx] if last_user_idx is not None else None
        history_before_latest = messages[:last_user_idx] if last_user_idx is not None else messages
        passthrough_slice = run_slice(history_before_latest, passthrough_runs)

        if not default_sections:
            curated_history: List[ModelMessage] = []
            if chat_instruction_message:
                curated_history.append(chat_instruction_message)
            curated_history.extend(passthrough_slice)
            if latest_user_message is not None:
                curated_history.append(latest_user_message)
            return curated_history

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

        if template_token_threshold > 0:
            estimate_parts: List[str] = []
            for m in messages:
                role, text = extract_role_and_text(m)
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
                passthrough_slice = run_slice(history_before_latest, -1)
                curated_history: List[ModelMessage] = []
                if chat_instruction_message:
                    curated_history.append(chat_instruction_message)
                curated_history.extend(passthrough_slice)
                if latest_user_message is not None:
                    curated_history.append(latest_user_message)
                return curated_history

        run_buffer_store = BufferStore()
        session_buffer_store = getattr(run_context.deps, "buffer_store", None)
        buffer_store_registry = {"run": run_buffer_store}
        if session_buffer_store is not None:
            buffer_store_registry["session"] = session_buffer_store
        exec_ctx = SectionExecutionContext(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
            model_alias=model_alias,
            template=template,
            registry=registry,
            week_start_day=week_start_day,
            manager_runs=manager_runs,
            recent_summaries_default=recent_summaries,
            run_context=run_context,
            cache_enabled=cache_enabled,
            cache_store=cache_store,
            cache_entry=cache_entry,
            section_cache=section_cache,
            run_scope_key=run_scope_key,
            run_buffer_store=run_buffer_store,
            buffer_store_registry=buffer_store_registry,
        )

        summary_messages: List[ModelMessage] = []
        persisted_sections: List[Dict[str, Any]] = []

        for idx, section in enumerate(default_sections):
            try:
                result = await run_context_section(
                    section=section,
                    section_index=idx,
                    messages=messages,
                    exec_ctx=exec_ctx,
                    manage_context_fn=manage_context,
                )
            except Exception as exc:  # pragma: no cover - defensive
                phase = getattr(exc, "phase", "section_execution")
                section_name = getattr(exc, "section_name", section.name)
                template_pointer = getattr(exc, "template_pointer", f"## {section.name}")
                logger.warning(
                    "Context management failed in history processor",
                    metadata={
                        "error": str(exc),
                        "phase": phase,
                        "section_name": section_name,
                        "template_pointer": template_pointer,
                    },
                )
                warning = (
                    CONTEXT_TEMPLATE_ERROR_HANDOFF_INSTRUCTION
                    +
                    f"section={section_name}; "
                    f"phase={phase}; "
                    f"template_pointer={template_pointer}; "
                    f"message={exc}"
                )
                summary_messages.append(
                    ModelRequest(parts=[SystemPromptPart(content=warning)])
                )
                continue
            summary_messages.extend(result.summary_messages)
            persisted_sections.extend(result.persisted_sections)

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
