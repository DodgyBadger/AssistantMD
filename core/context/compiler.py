from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional

from core.directives.model import ModelDirective
from core.llm.agents import create_agent
from core.context.templates import TemplateRecord
from core.logger import UnifiedLogger
from pydantic_ai.messages import ModelMessage

logger = UnifiedLogger(tag="context-compiler")

# Shared instruction prefix for the context compiler
COMPILER_SYSTEM_NOTE = """
You are part of a chat flow but you are NOT interacting directly with the user.
Your job is to condense and summarize the discussion so the primary chat agent 
stays focused on the main topic or goalgoal, avoids context rot, 
and feels like it has an endless context window.

You are provided with:
- Recent conversation history (message history)
- The latest context summary
- An extraction template describing what to extract and how to structure it

The instructions and fields referred to in the extraction template 
always relate to the conversation history. E.g. if the extraction template includes 
a field called "rules", that means rules relating to the chat topic or plan, if present.

- Respond ONLY with JSON matching the template’s structure. Do not add commentary, chatty text, or Markdown.
- Do not invent content. Everything you output must be sourced from the history provided.
- If a field or instruction in the extraction template is not relevant, simply output "N/A"
"""


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
    instructions = base_instructions

    prompt = "Context data:\n" + json.dumps(input_data.context_payload, ensure_ascii=False, indent=2)

    agent = await create_agent(
        instructions=instructions,
        model=model_instance,
        output_type=Dict[str, Any],
    )
    result = await agent.run(prompt, message_history=input_data.message_history)
    result_output = getattr(result, "output", None)

    parsed = result_output if isinstance(result_output, dict) else None
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
