from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional

from core.directives.model import ModelDirective
from core.llm.agents import create_agent
from core.context.templates import TemplateRecord
from core.logger import UnifiedLogger
from core.constants import CONTEXT_COMPILER_SYSTEM_NOTE
from pydantic_ai.messages import ModelMessage

logger = UnifiedLogger(tag="context-compiler")


@dataclass
class CompileInput:
    """Minimal inputs needed to compile a working context."""

    model_alias: str
    template: TemplateRecord
    context_payload: Dict[str, Any]
    message_history: Optional[List[ModelMessage]] = None


@dataclass
class CompileResult:
    """Result of a compilation run."""

    raw_output: str
    parsed_json: Optional[Dict[str, Any]]
    template: TemplateRecord
    model_alias: str


def _strip_code_fences(text: str) -> str:
    """Remove surrounding markdown code fences if present."""
    if "```" not in text:
        return text.strip()

    lines = text.strip().splitlines()
    if not lines:
        return text.strip()

    if lines[0].strip().startswith("```") and lines[-1].strip().startswith("```"):
        return "\n".join(lines[1:-1]).strip()

    return text.strip()


async def compile_context(
    input_data: CompileInput,
    instructions_override: Optional[str] = None,
    tools: Optional[List[Any]] = None,
) -> CompileResult:
    """
    Compile a concise working context using the provided template and model.

    This is a simple, best-effort compiler:
    - Uses the template content as instructions
    - Sends structured context data as the prompt
    - Attempts to parse JSON from the model output; if parsing fails, returns raw text
    """
    # Resolve model instance
    model_directive = ModelDirective()
    model_instance = model_directive.process_value(input_data.model_alias, "context-compiler")

    # Prepare agent system prompt: compiler note + template; user prompt = latest user input (if provided)
    system_prompt = instructions_override if instructions_override is not None else "\n\n".join(
        part for part in [
            CONTEXT_COMPILER_SYSTEM_NOTE,
            "Extraction template:",
            (input_data.template.content or "").strip(),
        ] if part
    )

    latest_input = input_data.context_payload.get("latest_input") if isinstance(input_data.context_payload, dict) else None
    prompt = latest_input or "No user input provided."

    agent = await create_agent(
        instructions=system_prompt,
        model=model_instance,
        tools=tools,
    )
    result = await agent.run(prompt, message_history=input_data.message_history)
    result_output = getattr(result, "output", None)

    parsed = result_output if isinstance(result_output, dict) else None
    if parsed is None and isinstance(result_output, str):
        # Try a best-effort JSON parse for models that return stringified JSON
        try:
            parsed = json.loads(_strip_code_fences(result_output))
        except Exception:
            parsed = None
    try:
        raw_output = json.dumps(result_output, ensure_ascii=False) if not isinstance(result_output, str) else result_output
    except Exception:
        raw_output = str(result_output)

    return CompileResult(
        raw_output=raw_output,
        parsed_json=parsed,
        template=input_data.template,
        model_alias=input_data.model_alias,
    )
