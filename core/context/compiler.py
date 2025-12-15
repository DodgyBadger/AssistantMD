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
from core.constants import CONTEXT_COMPILER_PROMPT, CONTEXT_COMPILER_SYSTEM_INSTRUCTION
from pydantic_ai.messages import (
    BuiltinToolReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolReturnPart,
)
from core.context.store import add_context_summary, upsert_session

logger = UnifiedLogger(tag="context-compiler")


@dataclass
class CompileInput:
    """Minimal inputs needed to compile a working context."""

    model_alias: str
    template: TemplateRecord
    context_payload: Dict[str, Any]


@dataclass
class CompileResult:
    """Result of a compilation run."""

    raw_output: str
    template: TemplateRecord
    model_alias: str


async def compile_context(
    input_data: CompileInput,
    instructions_override: Optional[str] = None,
    tools: Optional[List[Any]] = None,
) -> CompileResult:
    """
    Compile a concise working context using the provided template and model.

    Patterns:
    - Minimal compiler instruction added via agent.instructions (no system_prompt)
    - Compiler prompt + template content + rendered history + latest input become the user prompt
    - No message_history passed to the compiler agent (stateless per call)
    - Returns natural language output
    """
    # Resolve model instance
    model_directive = ModelDirective()
    model_instance = model_directive.process_value(input_data.model_alias, "context-compiler")

    compiler_instruction = instructions_override if instructions_override is not None else CONTEXT_COMPILER_SYSTEM_INSTRUCTION
    latest_input = input_data.context_payload.get("latest_input") if isinstance(input_data.context_payload, dict) else None
    rendered_history = input_data.context_payload.get("rendered_history") if isinstance(input_data.context_payload, dict) else None
    prompt_parts: List[str] = []
    prompt_parts.append(f"## Compiler task\n{CONTEXT_COMPILER_PROMPT}")
    base_template = (input_data.template.content or "").strip()
    if base_template:
        prompt_parts.append(f"## Extraction template\n{base_template}")
    if rendered_history:
        prompt_parts.append(f"## Recent conversation\n{rendered_history}")
    if latest_input:
        prompt_parts.append(f"## Latest user input\n{latest_input}")
    prompt = "\n\n".join(prompt_parts).strip() or "No content provided."

    agent = await create_agent(
        model=model_instance,
        tools=tools,
    )
    agent.instructions(lambda _ctx, text=compiler_instruction: text)
    result = await agent.run(prompt)
    result_output = getattr(result, "output", None)

    raw_output = str(result_output)

    return CompileResult(
        raw_output=raw_output,
        template=input_data.template,
        model_alias=input_data.model_alias,
    )


def build_compiling_history_processor(
    *,
    session_id: str,
    vault_name: str,
    vault_path: str,
    model_alias: str,
    template_name: str,
    recent_turns: int = 3,
)-> list[ModelMessage]:
    """
    Factory for a history processor that compiles a curated view and injects it
    as a system message ahead of the recent turns. If compilation fails, the
    original history is returned unchanged.
    """

    template = load_template(template_name, Path(vault_path))

    async def processor(run_context: RunContext[Any], messages: List[ModelMessage]) -> List[ModelMessage]:
        if not messages:
            return []

        # Trim based on non-tool turns, but preserve any tool messages between them
        if recent_turns > 0:
            non_tool_indices = [idx for idx, m in enumerate(messages) if not getattr(m, "tool_name", None)]
            if not non_tool_indices:
                start_idx = max(len(messages) - recent_turns, 0)
            else:
                start_idx = non_tool_indices[-recent_turns] if len(non_tool_indices) >= recent_turns else 0

            # Ensure tool return parts keep their preceding tool call message
            for idx in range(start_idx, len(messages)):
                msg = messages[idx]
                parts = getattr(msg, "parts", None)
                if parts and any(isinstance(p, (ToolReturnPart, BuiltinToolReturnPart)) for p in parts):
                    if idx > 0 and start_idx > idx - 1:
                        start_idx = idx - 1
                    break

            recent_slice = messages[start_idx:]
        else:
            recent_slice = messages

        # Render the recent slice into a simple text transcript.
        def _extract_role_and_text(msg: ModelMessage) -> tuple[str, str]:
            # Normalize role names across message types
            if isinstance(msg, ModelRequest):
                role = "user"
            elif isinstance(msg, ModelResponse):
                role = "assistant"
            else:
                role = getattr(msg, "role", None) or msg.__class__.__name__.lower()
            # Try direct content first
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content:
                return role, content
            # Fall back to parts if present (e.g., ModelRequest)
            parts = getattr(msg, "parts", None)
            if parts:
                texts = []
                for part in parts:
                    if isinstance(part, (ToolReturnPart, BuiltinToolReturnPart)):
                        # Skip tool return parts so they are not mis-rendered as user text
                        continue
                    part_content = getattr(part, "content", None)
                    if isinstance(part_content, str):
                        texts.append(part_content)
                if texts:
                    return role, "\n".join(texts)
            return role, ""

        rendered_lines: List[str] = []
        latest_input = ""
        for m in recent_slice:
            role, text = _extract_role_and_text(m)
            if text:
                rendered_lines.append(f"{role.capitalize()}: {text}")
            if role.lower() == "user" and text:
                latest_input = text

        rendered_history = "\n".join(rendered_lines)
        cache_store = getattr(run_context.deps, "context_compiler_cache", None)
        if cache_store is None:
            cache_store = {}
            try:
                setattr(run_context.deps, "context_compiler_cache", cache_store)
            except Exception:
                cache_store = {}
        run_scope_key = run_context.run_id or "default_run"
        cache_entry = cache_store.get(run_scope_key, {})

        summary_message: Optional[ModelMessage] = None

        try:
            compiled_output: Optional[str] = cache_entry.get("raw_output")

            if compiled_output is None:
                compile_input = CompileInput(
                    model_alias=model_alias,
                    template=template,
                    context_payload={
                        "latest_input": latest_input,
                        "rendered_history": rendered_history,
                    },
                )
                compiled_obj = await compile_context(
                    compile_input,
                    instructions_override=None,
                    tools=None,
                )
                compiled_output = compiled_obj.raw_output
                cache_entry = {
                    "raw_output": compiled_output,
                    "persisted": False,
                }
                cache_store[run_scope_key] = cache_entry

            # Persist the compiled view for observability.
            if cache_entry and not cache_entry.get("persisted"):
                try:
                    upsert_session(session_id=session_id, vault_name=vault_name, metadata=None)
                    add_context_summary(
                        session_id=session_id,
                        vault_name=vault_name,
                        turn_index=None,
                        template=template,
                        model_alias=model_alias,
                        summary_json=None,
                        raw_output=compiled_output,
                        budget_used=None,
                        sections_included=None,
                        compiled_prompt=None,
                        input_payload={"latest_input": latest_input},
                    )
                    cache_entry["persisted"] = True
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to persist compiled context summary", metadata={"error": str(exc)})

            summary_text = compiled_output or "N/A"
            summary_message = ModelRequest(parts=[SystemPromptPart(content=f"Context summary (compiled):\n{summary_text}")])
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Context compilation failed in history processor", metadata={"error": str(exc)})
            return list(messages)

        curated_history: List[ModelMessage] = []
        if summary_message:
            curated_history.append(summary_message)
        curated_history.extend(recent_slice)
        return curated_history

    return processor
