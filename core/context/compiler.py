from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.directives.model import ModelDirective
from core.llm.agents import create_agent
from core.context.templates import TemplateRecord
from core.logger import UnifiedLogger
from pydantic_ai.messages import ModelMessage

logger = UnifiedLogger(tag="context-compiler")

# Shared instruction prefix for the context compiler (templated with recent_turns)
COMPILER_SYSTEM_NOTE = """
You are the first step in the chat flow. Your job is to condense and summarize the discussion
so the primary chat agent stays focused, avoids context rot, and feels like it has an endless
context window. Output a concise, structured context summary.

You are provided with:
- The last {recent_turns} turns of the conversation (via message history)
- The latest context summary
- A template of what to focus your summary on and how to structure the output

Requirements:
- Prefer succinct bullet points over long prose
- Do not invent goals or constraints
- Preserve any non-negotiable constraints, decisions, and safety boundaries
- Do NOT restate the last {recent_turns} turns; they are already in message history
"""


@dataclass
class CompileInput:
    """Minimal inputs needed to compile a working context."""

    model_alias: str
    template: TemplateRecord
    topic: Optional[str] = None
    constraints: Optional[List[str]] = None
    plan: Optional[str] = None
    recent_turns: Optional[List[Dict[str, str]]] = None
    tool_results: Optional[List[Dict[str, str]]] = None
    reflections: Optional[List[Dict[str, str]]] = None
    latest_input: Optional[str] = None


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


async def compile_context(input_data: CompileInput, instructions_override: Optional[str] = None) -> CompileResult:
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

    # Prepare agent with template instructions
    base_instructions = instructions_override or input_data.template.content.strip()
    instructions = f"""{base_instructions}

Return JSON. If you cannot satisfy the schema, return the closest well-formed JSON you can."""

    # Build context payload for the model
    payload = {
        "topic": input_data.topic,
        "constraints": input_data.constraints or [],
        "plan": input_data.plan,
        "recent_turns": input_data.recent_turns or [],
        "tool_results": input_data.tool_results or [],
        "reflections": input_data.reflections or [],
        "latest_input": input_data.latest_input,
    }

    prompt = "Context data:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    agent = await create_agent(instructions=instructions, model=model_instance)
    message_history: Optional[List[ModelMessage]] = None
    if input_data.recent_turns:
        message_history = []
        for turn in input_data.recent_turns:
            speaker = turn.get("speaker") or "assistant"
            text = turn.get("text") or ""
            if not text:
                continue
            role = speaker.lower()
            if role not in ("user", "assistant", "system"):
                role = "assistant"
            message_history.append(ModelMessage(role=role, content=text))

    result = await agent.run(prompt, message_history=message_history)
    raw_output = result.output if hasattr(result, "output") else str(result)

    parsed = None
    cleaned = _strip_code_fences(raw_output)
    try:
        parsed = json.loads(cleaned)
    except Exception:
        logger.warning("Context compiler returned non-JSON; storing raw output", metadata={"output_preview": raw_output[:200]})

    return CompileResult(
        raw_output=raw_output,
        parsed_json=parsed,
        template=input_data.template,
        model_alias=input_data.model_alias,
    )
