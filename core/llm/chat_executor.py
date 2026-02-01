"""
Chat execution logic for dynamic prompt execution.

Handles stateful/stateless chat with user-selected tools and models.
Persists chat history to markdown files for auditability and testing.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, AsyncIterator, Any
from pathlib import Path

from pydantic_ai.messages import ModelMessage
from pydantic_ai import (
    PartStartEvent, PartDeltaEvent, AgentRunResultEvent,
    TextPartDelta, FunctionToolCallEvent, FunctionToolResultEvent
)

from core.llm.agents import create_agent
from core.llm.session_manager import SessionManager
from core.constants import (
    REGULAR_CHAT_INSTRUCTIONS,
    ASSISTANTMD_ROOT_DIR,
    CHAT_SESSIONS_DIR,
)
from core.directives.model import ModelDirective
from core.directives.tools import ToolsDirective
from core.context.manager import build_context_manager_history_processor
from core.context.templates import load_template
from core.settings.store import get_general_settings
from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context, has_runtime_context
from core.runtime.buffers import BufferStore


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


def _sanitize_session_id(session_id: str) -> str:
    """
    Constrain session ids to a safe filename segment.

    Replaces disallowed characters (including path separators) with underscores.
    """
    if not session_id:
        return "session"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", session_id)
    safe = safe.strip("._-")
    return safe or "session"


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


def _get_default_context_template() -> Optional[str]:
    """
    Return the configured default context template name, if set.
    """
    try:
        entry = get_general_settings().get("default_context_template")
        if entry and entry.value:
            return str(entry.value).strip() or None
    except Exception:
        return None
    return None


def _resolve_context_template_name(vault_path: str, context_template: Optional[str]) -> str:
    """
    Resolve a context template name with vault overrides and fallback to unmanaged chat.
    """
    fallback = "default.md"
    candidate = context_template or _get_default_context_template() or fallback
    try:
        load_template(candidate, Path(vault_path))
        return candidate
    except FileNotFoundError:
        if candidate != fallback:
            try:
                load_template(fallback, Path(vault_path))
            except Exception:
                return fallback
            return fallback
        return fallback
    except Exception:
        return fallback


@dataclass
class ChatExecutionResult:
    """Result of chat prompt execution."""
    response: str
    session_id: str
    message_count: int
    compiled_context_path: Optional[str] = None
    history_file: Optional[str] = None  # Path to saved chat history file


@dataclass
class ChatRunDeps:
    """Per-run dependencies/caches for chat agents."""
    context_manager_cache: dict[str, Any] = field(default_factory=dict)
    context_manager_now: Optional[datetime] = None
    buffer_store: BufferStore = field(default_factory=BufferStore)


def _resolve_context_manager_now() -> Optional[datetime]:
    if not has_runtime_context():
        return None
    try:
        runtime = get_runtime_context()
    except Exception:
        return None
    features = runtime.config.features or {}
    raw_value = features.get("context_manager_now")
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            return None
    return None


def save_chat_history(vault_path: str, session_id: str, prompt: str, response: str):
    """
    Append chat exchange to history file.

    Saves to {vault_path}/AssistantMD/Chat_Sessions/{session_id}.md
    """
    sessions_dir = Path(vault_path) / ASSISTANTMD_ROOT_DIR / CHAT_SESSIONS_DIR
    sessions_dir.mkdir(parents=True, exist_ok=True)

    safe_session_id = _sanitize_session_id(session_id)
    history_file = sessions_dir / f"{safe_session_id}.md"
    resolved_history = history_file.resolve()
    resolved_sessions = sessions_dir.resolve()
    if resolved_sessions not in resolved_history.parents:
        raise ValueError("Resolved chat history path is outside the chat sessions directory.")
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


def _prepare_agent_config(
    vault_name: str,
    vault_path: str,
    tools: List[str],
    model: str,
    instructions: Optional[str],
) -> tuple:
    """
    Prepare agent configuration (shared between streaming and non-streaming).

    Returns:
        Tuple of (base_instructions, tool_instructions, model_instance, tool_functions)
    """
    # Select base instructions
    if instructions:
        base_instructions = instructions  # Custom instructions override
    else:
        base_instructions = REGULAR_CHAT_INSTRUCTIONS

    # Process tools directive to get tool functions
    tool_functions = []
    tool_instructions = ""

    if tools:  # Only process if tools list is not empty
        tools_directive = ToolsDirective()
        tools_value = ", ".join(tools)  # Convert list to comma-separated string
        tool_functions, tool_instructions, _ = tools_directive.process_value(
            tools_value,
            vault_path=vault_path
        )

    # Process model directive to get Pydantic AI model instance
    model_directive = ModelDirective()
    model_instance = model_directive.process_value(model, f"{vault_name}/chat")

    return base_instructions, tool_instructions, model_instance, tool_functions


async def execute_chat_prompt(
    vault_name: str,
    vault_path: str,
    prompt: str,
    session_id: str,
    tools: List[str],
    model: str,
    session_manager: SessionManager,
    instructions: Optional[str] = None,
    context_template: Optional[str] = None,    
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
        instructions: Optional system instructions (defaults to regular chat instructions)

    Returns:
        ChatExecutionResult with response and session metadata
    """
    # Prepare agent configuration (shared logic)
    base_instructions, tool_instructions, model_instance, tool_functions = _prepare_agent_config(
        vault_name, vault_path, tools, model, instructions
    )

    resolved_template = _resolve_context_template_name(vault_path, context_template)
    history_processors = [
        build_context_manager_history_processor(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
            model_alias=model,
            template_name=resolved_template,
        )
    ]

    # Create agent with user-selected configuration
    agent = await create_agent(
        model=model_instance,
        tools=tool_functions if tool_functions else None,
        history_processors=history_processors,
    )
    for inst in [base_instructions, tool_instructions]:
        if inst:
            agent.instructions(lambda _ctx, text=inst: text)

    # Get message history (always tracked now)
    message_history: Optional[List[ModelMessage]] = session_manager.get_history(session_id, vault_name)

    # Run agent
    run_deps = ChatRunDeps(context_manager_now=_resolve_context_manager_now())
    result = await agent.run(
        prompt,
        message_history=message_history,
        deps=run_deps,
    )

    # Store new messages in session for next turn
    session_manager.add_messages(session_id, vault_name, result.new_messages())

    # Save chat history to markdown file
    history_file = save_chat_history(vault_path, session_id, prompt, result.output)
    logger.info(
        "Chat executed",
        data={
            "vault_name": vault_name,
            "session_id": session_id,
            "model": model,
            "tools_count": len(tools),
            "prompt_length": len(prompt),
            "history_file": history_file,
        },
    )

    return ChatExecutionResult(
        response=result.output,
        session_id=session_id,
        message_count=len(result.all_messages()),
        history_file=history_file
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
    context_template: Optional[str] = None,
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
        instructions: Optional system instructions (defaults to regular chat instructions)

    Yields:
        SSE-formatted chunks in OpenAI-compatible format
    """
    # Prepare agent configuration (shared logic)
    base_instructions, tool_instructions, model_instance, tool_functions = _prepare_agent_config(
        vault_name, vault_path, tools, model, instructions
    )

    resolved_template = _resolve_context_template_name(vault_path, context_template)
    history_processors = [
        build_context_manager_history_processor(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
            model_alias=model,
            template_name=resolved_template,
        )
    ]

    # Create agent with user-selected configuration
    agent = await create_agent(
        model=model_instance,
        tools=tool_functions if tool_functions else None,
        history_processors=history_processors,
    )
    for inst in [base_instructions, tool_instructions]:
        if inst:
            agent.instructions(lambda _ctx, text=inst: text)

    # Get message history
    message_history: Optional[List[ModelMessage]] = session_manager.get_history(session_id, vault_name)

    # Stream response and capture final result for history storage
    full_response = ""
    final_result = None
    tool_activity: dict[str, dict[str, Any]] = {}
    run_deps = ChatRunDeps(context_manager_now=_resolve_context_manager_now())

    try:
        # Use run_stream_events() to properly handle tool calls
        # This runs the agent graph to completion and streams all events
        async for event in agent.run_stream_events(
            prompt,
            message_history=message_history,
            deps=run_deps,
        ):
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

    # Save chat history to markdown file
    if final_result:
        save_chat_history(vault_path, session_id, prompt, full_response)
