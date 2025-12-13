"""
Chat execution logic for dynamic prompt execution.

Handles stateful/stateless chat with user-selected tools and models.
Persists chat history to markdown files for auditability and testing.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, AsyncIterator, Any, Dict
from pathlib import Path

from pydantic_ai.messages import ModelMessage
from pydantic_ai import (
    PartStartEvent, PartDeltaEvent, AgentRunResultEvent,
    TextPartDelta, FunctionToolCallEvent, FunctionToolResultEvent
)

from core.llm.agents import create_agent
from core.llm.session_manager import SessionManager
from core.constants import (
    WORKFLOW_CREATION_INSTRUCTIONS,
    REGULAR_CHAT_INSTRUCTIONS,
    ASSISTANTMD_ROOT_DIR,
    CHAT_SESSIONS_DIR,
)
from core.directives.model import ModelDirective
from core.directives.tools import ToolsDirective
from core.context.templates import load_template
from core.context.compiler import compile_context, CompileInput, COMPILER_SYSTEM_NOTE
from core.context.store import add_context_summary, upsert_session, get_latest_summary
from core.settings.store import get_general_settings
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="chat-executor")


def _truncate_preview(value: Optional[str], limit: int = 200) -> Optional[str]:
    """
    Safely truncate long strings for streaming metadata.

    Returns the original value if within limit, otherwise appends ellipsis.
    """
    if not value:
        return value
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _normalize_tool_args(args: Any) -> Optional[str]:
    """
    Convert tool call arguments to a compact JSON/string representation.
    """
    if args is None:
        return None
    if isinstance(args, str):
        return _truncate_preview(args.strip())
    try:
        serialized = json.dumps(args, ensure_ascii=False)
        return _truncate_preview(serialized)
    except (TypeError, ValueError):
        return _truncate_preview(str(args))


def _normalize_tool_result(result: Any) -> Optional[str]:
    """
    Convert tool results into a readable preview string.
    """
    if result is None:
        return None
    if isinstance(result, str):
        return _truncate_preview(result.strip(), limit=240)
    try:
        serialized = json.dumps(result, ensure_ascii=False)
        return _truncate_preview(serialized, limit=240)
    except (TypeError, ValueError):
        return _truncate_preview(str(result), limit=240)


@dataclass
class ChatExecutionResult:
    """Result of chat prompt execution."""
    response: str
    session_id: str
    message_count: int
    compiled_context_path: Optional[str] = None
    history_file: Optional[str] = None  # Path to saved chat history file


def save_chat_history(vault_path: str, session_id: str, prompt: str, response: str):
    """
    Append chat exchange to history file.

    Saves to {vault_path}/AssistantMD/Chat_Sessions/{session_id}.md
    """
    sessions_dir = Path(vault_path) / ASSISTANTMD_ROOT_DIR / CHAT_SESSIONS_DIR
    sessions_dir.mkdir(parents=True, exist_ok=True)

    history_file = sessions_dir / f"{session_id}.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create file with header if it doesn't exist
    if not history_file.exists():
        with open(history_file, 'w') as f:
            f.write(f"Chat Session: {session_id}\n\n")

    # Append exchange
    with open(history_file, 'a') as f:
        f.write(f"*{timestamp}*\n\n")
        f.write(f"**User:**\n {prompt}\n\n")
        f.write(f"**Assistant:**\n {response}\n\n")

    return str(history_file)


def _get_compiler_settings():
    """Fetch compiler-related settings with safe fallbacks."""
    settings = get_general_settings()

    def _get_int(key: str, default: int) -> int:
        try:
            return int(settings.get(key).value)
        except Exception:
            return default

    return {
        "recent_turns": _get_int("context_compiler_recent_turns", 3),
        "recent_tool_results": _get_int("context_compiler_recent_tool_results", 3),
        "max_tokens": _get_int("context_compiler_max_tokens", 4000),
    }


def _prepare_agent_config(
    vault_name: str,
    vault_path: str,
    tools: List[str],
    model: str,
    instructions: Optional[str],
    session_type: str
) -> tuple:
    """
    Prepare agent configuration (shared between streaming and non-streaming).

    Returns:
        Tuple of (final_instructions, model_instance, tool_functions)
    """
    # Select base instructions by session type
    if session_type == "workflow_creation":
        base_instructions = WORKFLOW_CREATION_INSTRUCTIONS
    elif instructions:
        base_instructions = instructions  # Custom instructions override
    else:
        base_instructions = REGULAR_CHAT_INSTRUCTIONS

    # Process tools directive to get tool functions
    tool_functions = []
    tool_instructions = ""

    if tools:  # Only process if tools list is not empty
        tools_directive = ToolsDirective()
        tools_value = ", ".join(tools)  # Convert list to comma-separated string
        tool_functions, tool_instructions = tools_directive.process_value(
            tools_value,
            vault_path=vault_path
        )

    # Compose instructions using Pydantic AI's list support for clean composition
    if tool_functions and tool_instructions:
        final_instructions = [base_instructions, tool_instructions]
    else:
        final_instructions = base_instructions

    # Process model directive to get Pydantic AI model instance
    model_directive = ModelDirective()
    model_instance = model_directive.process_value(model, f"{vault_name}/chat")

    return final_instructions, model_instance, tool_functions


async def execute_chat_prompt(
    vault_name: str,
    vault_path: str,
    prompt: str,
    session_id: str,
    tools: List[str],
    model: str,
    session_manager: SessionManager,
    instructions: Optional[str] = None,
    session_type: str = "regular",
    context_template: Optional[str] = None,
    turn_index: Optional[int] = None,
) -> ChatExecutionResult:
    """
    Execute chat prompt with user-selected tools and model.

    Args:
        vault_name: Vault name for session tracking
        vault_path: Full path to vault directory
        prompt: User's prompt text
        session_id: Session identifier for conversation tracking
        tools: List of tool names selected by user
        model: Model name selected by user
        session_manager: Session manager instance for history storage
        instructions: Optional system instructions (defaults based on session_type)
        session_type: Chat mode ("regular" or "workflow_creation")

    Returns:
        ChatExecutionResult with response and session metadata
    """
    # Prepare agent configuration (shared logic)
    final_instructions, model_instance, tool_functions = _prepare_agent_config(
        vault_name, vault_path, tools, model, instructions, session_type
    )

    # Endless mode: compile context instead of using full history
    compiled_summary = None
    compiled_prompt_text = None
    input_payload = None

    if session_type == "endless":
        settings = _get_compiler_settings()
        template = load_template(context_template, Path(vault_path))

        # Try to reuse prior compiled summary to seed state
        prior_summary = get_latest_summary(session_id, vault_name)

        history_messages: List[ModelMessage] = session_manager.get_history(session_id, vault_name) or []

        # Last N turns to pass into compiler (and agent)
        take_turns = settings["recent_turns"]
        recent_history = session_manager.get_recent_matching(
            session_id,
            vault_name,
            take_turns,
            lambda m: not getattr(m, "tool_name", None),
        )

        # Collect recent tool results from history if available
        recent_tool_results: List[Dict[str, Any]] = []
        tool_messages = session_manager.get_recent_matching(
            session_id,
            vault_name,
            settings["recent_tool_results"],
            lambda m: bool(getattr(m, "tool_name", None)),
        )
        for msg in tool_messages:
            recent_tool_results.append(
                {
                    "tool": getattr(msg, "tool_name", None),
                    "result": getattr(msg, "content", None),
                }
            )

        input_payload = {
            "topic": prior_summary.get("topic") if isinstance(prior_summary, dict) else None,
            "constraints": prior_summary.get("constraints") if isinstance(prior_summary, dict) else [],
            "plan": prior_summary.get("plan") if isinstance(prior_summary, dict) else None,
            "tool_results": recent_tool_results,
            "reflections": prior_summary.get("reflections") if isinstance(prior_summary, dict) else [],
            "latest_input": prompt,
        }

        compile_input = CompileInput(
            model_alias=model,
            template=template,
            context_payload=input_payload,
            message_history=recent_history,
        )

        try:
            compiler_instructions = COMPILER_SYSTEM_NOTE + "\n\n" + template.content
            compiled_summary = await compile_context(compile_input, instructions_override=compiler_instructions)
            compiled_prompt_text = compiled_summary.raw_output
        except Exception as exc:
            logger.warning(f"Context compiler failed for session {session_id}: {exc}")

    # Create agent with user-selected configuration
    agent = await create_agent(
        instructions=final_instructions,
        model=model_instance,
        tools=tool_functions if tool_functions else None
    )

    # Get message history (always tracked now)
    message_history: Optional[List[ModelMessage]] = None
    if session_type == "endless":
        take = _get_compiler_settings()["recent_turns"]
        message_history = session_manager.get_recent_matching(
            session_id,
            vault_name,
            take,
            lambda m: not getattr(m, "tool_name", None),
        )
    else:
        message_history = session_manager.get_history(session_id, vault_name)

    # Run agent with compiled prompt (endless) or direct prompt
    effective_prompt = prompt
    if session_type == "endless" and compiled_prompt_text:
        effective_prompt = f"Context summary:\n{compiled_prompt_text}\n\nUser input:\n{prompt}"

    result = await agent.run(effective_prompt, message_history=message_history)

    # Store new messages in session for next turn
    session_manager.add_messages(session_id, vault_name, result.new_messages())

    # Save chat history to markdown file
    history_file = save_chat_history(vault_path, session_id, prompt, result.output)

    # Persist compiled context summary if used
    compiled_context_path = None
    if compiled_summary:
        upsert_session(session_id=session_id, vault_name=vault_name, metadata=None)
        try:
            add_context_summary(
                session_id=session_id,
                vault_name=vault_name,
                turn_index=turn_index,
                template=template if 'template' in locals() else load_template(context_template, Path(vault_path)),
                model_alias=model,
                summary_json=compiled_summary.parsed_json,
                raw_output=compiled_summary.raw_output,
                budget_used=None,
                sections_included=None,
                compiled_prompt=compiled_prompt_text,
                input_payload=input_payload,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Failed to persist compiled context for session {session_id}: {exc}")

    return ChatExecutionResult(
        response=result.output,
        session_id=session_id,
        message_count=len(result.all_messages()),
        history_file=history_file,
        compiled_context_path=compiled_context_path,
    )


async def execute_chat_prompt_stream(
    vault_name: str,
    vault_path: str,
    prompt: str,
    session_id: str,
    tools: List[str],
    model: str,
    session_manager: SessionManager,
    instructions: Optional[str] = None,
    session_type: str = "regular",
    context_template: Optional[str] = None,
    turn_index: Optional[int] = None,
) -> AsyncIterator[str]:
    """
    Execute chat prompt with streaming response.

    Streams SSE-formatted chunks and captures conversation history for session storage.

    Args:
        vault_name: Vault name for session tracking
        vault_path: Full path to vault directory
        prompt: User's prompt text
        session_id: Session identifier for conversation tracking
        tools: List of tool names selected by user
        model: Model name selected by user
        session_manager: Session manager instance for history storage
        instructions: Optional system instructions (defaults based on session_type)
        session_type: Chat mode ("regular" or "workflow_creation")

    Yields:
        SSE-formatted chunks in OpenAI-compatible format
    """
    # Prepare agent configuration (shared logic)
    final_instructions, model_instance, tool_functions = _prepare_agent_config(
        vault_name, vault_path, tools, model, instructions, session_type
    )

    # Endless mode: compile context instead of using full history
    compiled_summary = None
    compiled_prompt_text = None
    input_payload = None

    if session_type == "endless":
        settings = _get_compiler_settings()
        template = load_template(context_template, Path(vault_path))

        history_messages: List[ModelMessage] = session_manager.get_history(session_id, vault_name) or []

        take_turns = settings["recent_turns"]
        recent_history = session_manager.get_recent_matching(
            session_id,
            vault_name,
            take_turns,
            lambda m: not getattr(m, "tool_name", None),
        )

        prior_summary = get_latest_summary(session_id, vault_name)

        tool_results: List[Dict[str, Any]] = []
        if isinstance(prior_summary, dict):
            prior_tools = prior_summary.get("tool_results")
            if isinstance(prior_tools, list):
                tool_results.extend(prior_tools)

        tool_messages = session_manager.get_recent_matching(
            session_id,
            vault_name,
            settings["recent_tool_results"],
            lambda m: bool(getattr(m, "tool_name", None)),
        )
        for msg in tool_messages:
            tool_results.append(
                {
                    "tool": getattr(msg, "tool_name", None),
                    "result": getattr(msg, "content", None),
                }
            )
        if settings["recent_tool_results"] > 0 and len(tool_results) > settings["recent_tool_results"]:
            tool_results = tool_results[-settings["recent_tool_results"] :]

        input_payload = {
            "topic": prior_summary.get("topic") if isinstance(prior_summary, dict) else None,
            "constraints": prior_summary.get("constraints") if isinstance(prior_summary, dict) else [],
            "plan": prior_summary.get("plan") if isinstance(prior_summary, dict) else None,
            "tool_results": tool_results,
            "reflections": prior_summary.get("reflections") if isinstance(prior_summary, dict) else [],
            "latest_input": prompt,
        }

        compile_input = CompileInput(
            model_alias=model,
            template=template,
            context_payload=input_payload,
            message_history=recent_history,
        )

        try:
            compiler_instructions = COMPILER_SYSTEM_NOTE + "\n\n" + template.content
            compiled_summary = await compile_context(compile_input, instructions_override=compiler_instructions)
            compiled_prompt_text = compiled_summary.raw_output
        except Exception as exc:
            logger.warning(f"Context compiler failed for session {session_id}: {exc}")

    # Create agent with user-selected configuration
    agent = await create_agent(
        instructions=final_instructions,
        model=model_instance,
        tools=tool_functions if tool_functions else None
    )

    # Get message history
    message_history: Optional[List[ModelMessage]] = None
    if session_type == "endless":
        take = _get_compiler_settings()["recent_turns"]
        message_history = session_manager.get_recent_matching(
            session_id,
            vault_name,
            take,
            lambda m: not getattr(m, "tool_name", None),
        )
    else:
        message_history = session_manager.get_history(session_id, vault_name)

    # Stream response and capture final result for history storage
    full_response = ""
    final_result = None
    tool_activity: dict[str, dict[str, Any]] = {}

    try:
        # Use run_stream_events() to properly handle tool calls
        # This runs the agent graph to completion and streams all events
        effective_prompt = prompt
        if session_type == "endless" and compiled_prompt_text:
            effective_prompt = f"Context summary:\n{compiled_prompt_text}\n\nUser input:\n{prompt}"
        async for event in agent.run_stream_events(effective_prompt, message_history=message_history):
            if isinstance(event, PartStartEvent):
                # Initial text part - send as first chunk
                if hasattr(event.part, 'content') and event.part.content:
                    delta_text = event.part.content
                    full_response += delta_text

                    chunk = {
                        "event": "delta",
                        "choices": [{
                            "delta": {"content": delta_text},
                            "index": 0,
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

            elif isinstance(event, PartDeltaEvent):
                # Incremental text delta
                if isinstance(event.delta, TextPartDelta):
                    delta_text = event.delta.content_delta
                    full_response += delta_text

                    chunk = {
                        "event": "delta",
                        "choices": [{
                            "delta": {"content": delta_text},
                            "index": 0,
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

            elif isinstance(event, FunctionToolCallEvent):
                # Tool is being called - optionally show progress
                tool_id = event.tool_call_id
                logger.info(f"Tool call started: {tool_id}")
                tool_part = getattr(event, "part", None)
                tool_name = getattr(tool_part, "tool_name", "tool")
                tool_args = None
                if tool_part is not None:
                    try:
                        tool_args = tool_part.args_as_json_str()
                    except Exception:  # noqa: BLE001 - defensive: upstream variations
                        tool_args = tool_part.args
                tool_activity[tool_id] = {
                    "tool_name": tool_name,
                    "status": "running"
                }
                metadata_chunk = {
                    "event": "tool_call_started",
                    "tool_call_id": tool_id,
                    "tool_name": tool_name,
                    "arguments": _normalize_tool_args(tool_args)
                }
                yield f"data: {json.dumps(metadata_chunk)}\n\n"

            elif isinstance(event, FunctionToolResultEvent):
                # Tool returned a result
                tool_id = event.tool_call_id
                logger.info(f"Tool result received: {tool_id}")
                result_part = getattr(event, "result", None)
                tool_name = getattr(result_part, "tool_name", "tool")
                result_content = None
                if result_part is not None:
                    try:
                        result_content = result_part.model_response_str()
                    except Exception:  # noqa: BLE001 - defensive fallback
                        result_content = getattr(result_part, "content", None)
                tool_activity[tool_id] = {
                    "tool_name": tool_name,
                    "status": "completed"
                }
                metadata_chunk = {
                    "event": "tool_call_finished",
                    "tool_call_id": tool_id,
                    "tool_name": tool_name,
                    "result": _normalize_tool_result(result_content)
                }
                yield f"data: {json.dumps(metadata_chunk)}\n\n"

            elif isinstance(event, AgentRunResultEvent):
                # Final result with complete message history
                final_result = event.result

        # Send final chunk with finish_reason
        final_chunk = {
            "event": "done",
            "choices": [{
                "delta": {},
                "index": 0,
                "finish_reason": "stop"
            }],
            "tool_summary": tool_activity
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {e}")
        error_chunk = {
            "event": "error",
            "choices": [{
                "delta": {"content": f"\n\n❌ Error: {str(e)}"},
                "index": 0,
                "finish_reason": "error"
            }]
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        raise

    # Store new messages in session (including tool results captured during stream)
    if final_result:
        session_manager.add_messages(session_id, vault_name, final_result.new_messages())
        # Add synthetic tool result messages so the compiler can see recent tool activity
        if tool_activity:
            synthetic_tool_messages: List[ModelMessage] = []
            for tool_id, meta in tool_activity.items():
                tool_name = meta.get("tool_name")
                result_preview = meta.get("result") or meta.get("arguments")
                if not tool_name or result_preview is None:
                    continue
                try:
                    msg = ModelMessage(role="tool", content=str(result_preview))
                    setattr(msg, "tool_name", tool_name)
                    synthetic_tool_messages.append(msg)
                except Exception:
                    continue
            if synthetic_tool_messages:
                session_manager.add_messages(session_id, vault_name, synthetic_tool_messages)

    # Save chat history to markdown file
    if final_result:
        save_chat_history(vault_path, session_id, prompt, full_response)

    # Persist compiled context summary if used
    if compiled_summary:
        upsert_session(session_id=session_id, vault_name=vault_name, metadata=None)
        try:
            add_context_summary(
                session_id=session_id,
                vault_name=vault_name,
                turn_index=turn_index,
                template=template if 'template' in locals() else load_template(context_template, Path(vault_path)),
                model_alias=model,
                summary_json=compiled_summary.parsed_json,
                raw_output=compiled_summary.raw_output,
                budget_used=None,
                sections_included=None,
                compiled_prompt=compiled_prompt_text,
                input_payload=input_payload,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Failed to persist compiled context for session {session_id}: {exc}")
