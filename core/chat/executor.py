"""
Chat execution logic for dynamic prompt execution.

Handles stateful/stateless chat with user-selected tools and models.
Persists canonical chat history in the structured chat store.
"""

import asyncio
import json
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import List, Optional, AsyncIterator, Any, Sequence
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart, TextPart, UserPromptPart
from pydantic_ai import (
    BinaryContent,
    PartStartEvent, PartDeltaEvent, AgentRunResultEvent,
    TextPartDelta, FunctionToolCallEvent, FunctionToolResultEvent
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import UserContent
from pydantic_ai.usage import UsageLimits

from core.llm.agents import create_agent
from core.chat.chat_store import ChatStore
from core.chat.compaction import (
    chat_session_history_lock,
    maybe_auto_compact_after_turn,
)
from core.constants import REGULAR_CHAT_INSTRUCTIONS
from core.llm.model_factory import build_model_instance
from core.llm.model_selection import ModelExecutionSpec, resolve_model_execution_spec
from core.llm.thinking import ThinkingValue, thinking_value_to_label
from core.authoring.shared.tool_binding import resolve_tool_binding
from core.llm.model_utils import (
    get_model_capabilities,
    model_supports_capability,
    resolve_model,
)
from core.authoring.context_manager import (
    ContextTemplateExecutionError,
    build_context_manager_history_processor,
)
from core.llm.capabilities.chat_context import build_context_template_error_details
from core.llm.capabilities.chat_tool_output_cache import tool_result_as_text
from core.llm.capabilities.factory import build_chat_capabilities
from core.settings import (
    get_chat_model_requests_limit,
    get_chat_tool_calls_limit,
    get_chunking_max_image_bytes_per_image,
    get_chunking_max_image_mb_per_image,
    get_default_model_thinking,
)
from core.logger import UnifiedLogger
from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSource,
    chat_session_scope,
    chat_task_label,
)
from core.runtime.state import get_runtime_context, has_runtime_context
from core.runtime.buffers import BufferStore, get_session_buffer_store
from core.tools.failures import classify_exception
from core.tools.utils import estimate_token_count


logger = UnifiedLogger(tag="chat-executor")


PromptInput = str | Sequence[UserContent]


_CHAT_STORE = ChatStore()
_LATEST_TURN_FAILURE_METADATA_KEY = "latest_turn_failure"


@dataclass(frozen=True)
class UploadedImageAttachment:
    """Direct chat image attachment sourced from request payload bytes."""

    display_name: str
    content: BinaryContent


class ChatCapabilityError(ValueError):
    """Raised when a chat request requires model capabilities that are unavailable."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class ChatContextTemplateError(ValueError):
    """Raised when a selected chat context template cannot be used."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class ChatToolCallLimitError(ValueError):
    """Raised when a chat run exceeds the configured tool-call limit."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class ChatModelRequestLimitError(ValueError):
    """Raised when a chat run exceeds the configured model-request limit."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


@dataclass
class PreparedChatExecution:
    """Preflighted chat execution state safe to reuse across sync and streaming paths."""

    agent: Any
    # Completed prior turns only. The active prompt is passed separately to
    # Pydantic AI and becomes canonical history through result.new_messages().
    message_history: Optional[List[ModelMessage]]
    prompt_for_history: str
    user_prompt: PromptInput
    attached_image_count: int
    model: str
    tools: List[str]
    context_template: Optional[str] = None
    workspace_path: str = ""


def _accepted_user_request(prepared: PreparedChatExecution) -> ModelRequest:
    """Build the accepted user turn persisted before model execution."""
    return ModelRequest(parts=[UserPromptPart(content=prepared.prompt_for_history)])


def _messages_after_accepted_user_request(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Drop the active user request that AssistantMD already persisted."""
    filtered: list[ModelMessage] = []
    skipped_accepted_user = False
    for message in messages:
        if not skipped_accepted_user and _is_user_prompt_request(message):
            skipped_accepted_user = True
            continue
        filtered.append(message)
    return filtered


def _is_user_prompt_request(message: ModelMessage) -> bool:
    if not isinstance(message, ModelRequest):
        return False
    return any(isinstance(part, UserPromptPart) for part in getattr(message, "parts", ()))


def _serialize_exception(exc: Exception) -> dict[str, Any]:
    """Return stable exception details for activity-log diagnostics."""
    return {
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).strip(),
    }


def _build_failure_recovery_marker(
    *,
    exc: Exception,
    phase: str,
    streaming: bool,
    model: str | None,
    tools: Sequence[str] | None,
    sequence_index: int,
) -> dict[str, Any]:
    """Build session metadata that lets the next turn recover from a failed run."""
    classification = classify_exception(exc, phase=phase)
    metadata = classification.to_metadata()
    return {
        "status": "failed",
        "phase": phase,
        "streaming": streaming,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "failure_kind": classification.failure_kind,
        "retryable": classification.retryable,
        "http_status": classification.http_status,
        "retry_after": classification.retry_after,
        "model": model,
        "tools": list(tools or []),
        "accepted_user_sequence_index": sequence_index,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suggested_action": (
            "Treat the previous user request as accepted but unfinished. "
            f"{metadata['suggested_action']}"
        ),
    }


def _record_latest_turn_failure(
    *,
    session_id: str,
    vault_name: str,
    exc: Exception,
    phase: str,
    streaming: bool,
    model: str | None,
    tools: Sequence[str] | None,
) -> None:
    """Persist an internal failure marker for a user turn with no assistant outcome."""
    marker = _build_failure_recovery_marker(
        exc=exc,
        phase=phase,
        streaming=streaming,
        model=model,
        tools=tools,
        sequence_index=_CHAT_STORE.get_highest_message_sequence_index(session_id, vault_name),
    )
    _CHAT_STORE.update_session_metadata(
        session_id=session_id,
        vault_name=vault_name,
        metadata_update={_LATEST_TURN_FAILURE_METADATA_KEY: marker},
        advance_history_revision=True,
    )
    logger.warning(
        "chat_turn_failure_marker_recorded",
        data={
            "event": "chat_turn_failure_marker_recorded",
            "vault_name": vault_name,
            "session_id": session_id,
            **marker,
        },
    )


def _clear_latest_turn_failure(*, session_id: str, vault_name: str) -> None:
    """Clear any internal failure marker after a successful assistant outcome."""
    metadata = _CHAT_STORE.get_session_metadata(session_id, vault_name)
    if _LATEST_TURN_FAILURE_METADATA_KEY not in metadata:
        return
    _CHAT_STORE.update_session_metadata(
        session_id=session_id,
        vault_name=vault_name,
        remove_keys=(_LATEST_TURN_FAILURE_METADATA_KEY,),
        advance_history_revision=True,
    )


def _failure_recovery_message(marker: dict[str, Any]) -> ModelRequest | None:
    """Render a metadata failure marker as ephemeral model context."""
    if marker.get("status") != "failed":
        return None
    phase = str(marker.get("phase") or "unknown")
    error_type = str(marker.get("error_type") or "Error")
    error = str(marker.get("error") or "").strip()
    sequence_index = marker.get("accepted_user_sequence_index")
    text = (
        "Internal recovery note: the previous user request was accepted into chat history "
        "but the assistant response failed before it was persisted. "
        f"Failure phase: {phase}. Error type: {error_type}."
    )
    failure_kind = str(marker.get("failure_kind") or "").strip()
    if failure_kind:
        text += f" Failure kind: {failure_kind}."
    if "retryable" in marker:
        text += f" Retryable: {bool(marker.get('retryable'))}."
    if error:
        text += f" Error: {error}."
    if sequence_index is not None:
        text += f" Accepted user message sequence index: {sequence_index}."
    suggested_action = str(marker.get("suggested_action") or "").strip()
    if suggested_action:
        text += f" Suggested action: {suggested_action}"
    text += (
        " For broad or long-running work, resume from durable state rather than assuming partial "
        "failed-run tool history was persisted: inspect goal_ops goals/checkpoints, vault activity, "
        "changed files, saved artifacts, and session history; then continue in a smaller checkpointed batch."
    )
    return ModelRequest(parts=[SystemPromptPart(content=text)])


def _with_failure_recovery_context(
    messages: list[ModelMessage] | None,
    *,
    session_id: str,
    vault_name: str,
) -> list[ModelMessage] | None:
    """Append ephemeral recovery context for an unfinished prior turn."""
    metadata = _CHAT_STORE.get_session_metadata(session_id, vault_name)
    marker = metadata.get(_LATEST_TURN_FAILURE_METADATA_KEY)
    if not isinstance(marker, dict):
        return messages
    recovery_message = _failure_recovery_message(marker)
    if recovery_message is None:
        return messages
    return [*(messages or []), recovery_message]


def _chat_usage_limits() -> UsageLimits | None:
    tool_calls_limit = get_chat_tool_calls_limit()
    model_requests_limit = get_chat_model_requests_limit()
    return UsageLimits(
        request_limit=model_requests_limit if model_requests_limit > 0 else None,
        tool_calls_limit=tool_calls_limit if tool_calls_limit > 0 else None,
    )


def _build_tool_call_limit_error(exc: UsageLimitExceeded) -> ChatToolCallLimitError:
    limit = get_chat_tool_calls_limit()
    limit_label = f" of {limit}" if limit > 0 else ""
    return ChatToolCallLimitError(
        (
            f"Chat stopped because it exceeded the configured tool-call limit"
            f"{limit_label}. "
            "Increase chat_tool_calls_limit or set it to 0 to disable this guard."
        ),
        details={
            "setting": "chat_tool_calls_limit",
            "limit": limit,
            "error_type": type(exc).__name__,
            "error": str(exc),
        },
    )


def _build_model_request_limit_error(exc: UsageLimitExceeded) -> ChatModelRequestLimitError:
    limit = get_chat_model_requests_limit()
    limit_label = f" of {limit}" if limit > 0 else ""
    return ChatModelRequestLimitError(
        (
            f"Chat stopped because it reached the configured model-request limit"
            f"{limit_label} for this run. "
            "The session is intact. Ask the agent to continue in a new message; it should resume "
            "from durable state such as goal_ops checkpoints, vault activity, changed files, saved "
            "artifacts, and session history. Increase chat_model_requests_limit only when the larger "
            "scope is intentional."
        ),
        details={
            "setting": "chat_model_requests_limit",
            "limit_kind": "request_limit",
            "limit": limit,
            "error_type": type(exc).__name__,
            "error": str(exc),
        },
    )


def _build_chat_usage_limit_error(exc: UsageLimitExceeded) -> ChatToolCallLimitError | ChatModelRequestLimitError:
    if "request_limit" in str(exc):
        return _build_model_request_limit_error(exc)
    return _build_tool_call_limit_error(exc)


def _usage_limit_label(error: ChatToolCallLimitError | ChatModelRequestLimitError) -> str:
    return "model-request limit" if isinstance(error, ChatModelRequestLimitError) else "tool-call limit"


def _usage_limit_display_label(error: ChatToolCallLimitError | ChatModelRequestLimitError) -> str:
    return "Model-request limit" if isinstance(error, ChatModelRequestLimitError) else "Tool-call limit"


def _chat_event_for_message(message: str) -> str | None:
    """Map existing chat lifecycle messages to stable activity event names."""
    if message in {"Chat execution started", "Streaming chat execution started"}:
        return "chat_turn_started"
    if message in {"Chat execution completed", "Streaming chat execution completed"}:
        return "chat_turn_completed"
    if message in {"Chat execution cancelled", "Streaming chat execution cancelled"}:
        return "chat_turn_cancelled"
    if "failed" in message.lower() or "limit exceeded" in message.lower():
        return "chat_turn_failed"
    return None


def _chat_status_for_event(event: str | None) -> str | None:
    """Return a normalized status label for chat activity events."""
    if event == "chat_turn_started":
        return "started"
    if event == "chat_turn_completed":
        return "completed"
    if event == "chat_turn_cancelled":
        return "cancelled"
    if event == "chat_turn_failed":
        return "failed"
    return None


def _summarize_tool_activity(tool_activity: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build compact tool-call counts for activity logs."""
    by_tool: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for item in tool_activity.values():
        tool_name = str(item.get("tool_name") or "tool")
        status = str(item.get("status") or "unknown")
        by_tool[tool_name] = by_tool.get(tool_name, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "tool_call_count": len(tool_activity),
        "tool_call_status_counts": by_status,
        "tool_call_tool_counts": by_tool,
    }


def _log_chat_lifecycle(
    message: str,
    *,
    vault_name: str,
    session_id: str,
    model: str | None = None,
    tools: Optional[List[str]] = None,
    streaming: bool,
    phase: str,
    prompt_length: int | None = None,
    attached_image_count: int | None = None,
    context_template: str | None = None,
    workspace_path: str | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Emit structured lifecycle logs for chat session execution."""
    event = _chat_event_for_message(message)
    payload: dict[str, Any] = {
        "vault_name": vault_name,
        "session_id": session_id,
        "streaming": streaming,
        "phase": phase,
    }
    if event:
        payload["event"] = event
        payload["status"] = _chat_status_for_event(event)
    if model is not None:
        payload["model"] = model
    if tools is not None:
        payload["tools"] = list(tools)
        payload["tools_count"] = len(tools)
    if context_template is not None:
        payload["context_template"] = context_template
    if workspace_path is not None:
        payload["workspace_path"] = workspace_path
    if prompt_length is not None:
        payload["prompt_length"] = prompt_length
    if attached_image_count is not None:
        payload["attached_image_count"] = attached_image_count
    rss_bytes = _get_process_rss_bytes()
    if rss_bytes is not None:
        payload["memory_rss_bytes"] = rss_bytes
    if extra:
        payload.update(extra)
    logger.info(message, data=payload)


def _log_chat_failure(
    message: str,
    *,
    vault_name: str,
    session_id: str,
    model: str | None = None,
    tools: Optional[List[str]] = None,
    streaming: bool,
    phase: str,
    prompt_length: int | None = None,
    attached_image_count: int | None = None,
    context_template: str | None = None,
    workspace_path: str | None = None,
    extra: Optional[dict[str, Any]] = None,
    exc: Exception,
) -> None:
    """Emit structured failure logs for chat session execution."""
    payload = _serialize_exception(exc)
    classification = classify_exception(exc, phase=phase)
    payload.update(classification.to_metadata())
    if extra:
        payload.update(extra)
    rss_bytes = _get_process_rss_bytes()
    if rss_bytes is not None:
        payload["memory_rss_bytes"] = rss_bytes
    event = _chat_event_for_message(message) or "chat_turn_failed"
    logger.error(
        message,
        data={
            "event": event,
            "status": _chat_status_for_event(event),
            "vault_name": vault_name,
            "session_id": session_id,
            "streaming": streaming,
            "phase": phase,
            "model": model,
            "tools": list(tools or []),
            "tools_count": len(tools or []),
            "context_template": context_template,
            "workspace_path": workspace_path,
            "prompt_length": prompt_length,
            "attached_image_count": attached_image_count,
            **payload,
        },
    )


async def _try_auto_compact_after_turn(
    *,
    session_id: str,
    vault_name: str,
    vault_path: str,
) -> None:
    """Run post-turn automatic compaction without failing the completed chat."""
    try:
        await maybe_auto_compact_after_turn(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Automatic chat history compaction failed after completed chat turn",
            data={
                "vault_name": vault_name,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


def _get_process_rss_bytes() -> int | None:
    """Return current process RSS in bytes when available."""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith("VmRSS:"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1]) * 1024
    except OSError:
        return None
    return None


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


def _normalize_tool_detail(value: Any) -> Any:
    """
    Convert streamed tool details into JSON-safe data without preview truncation.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        try:
            return json.loads(stripped)
        except (TypeError, ValueError):
            return stripped
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return str(value)


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


def _build_model_capability_details(
    model_alias: str,
    requested_capability: str,
    *,
    image_paths: Optional[List[str]] = None,
    image_uploads: Optional[List[UploadedImageAttachment]] = None,
) -> dict[str, Any]:
    """Collect stable context describing a model capability mismatch."""
    execution = resolve_model_execution_spec(model_alias)
    base_alias = execution.base_alias or model_alias.strip()
    provider = None
    model_string = None
    declared_capabilities = ["text"] if base_alias == "test" else []

    if base_alias and base_alias != "test":
        try:
            provider, model_string = resolve_model(base_alias)
        except ValueError:
            provider = None
            model_string = None
        try:
            declared_capabilities = sorted(get_model_capabilities(base_alias))
        except ValueError:
            declared_capabilities = []

    return {
        "model_alias": model_alias,
        "model_base_alias": base_alias,
        "provider": provider,
        "model_string": model_string,
        "requested_capability": requested_capability,
        "declared_capabilities": declared_capabilities,
        "image_path_count": sum(1 for path in (image_paths or []) if (path or "").strip()),
        "image_upload_count": len(image_uploads or []),
    }


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
    buffer_store_registry: dict[str, BufferStore] = field(default_factory=dict)
    session_id: str = ""
    vault_name: str = ""
    message_history: List[ModelMessage] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)


def _resolve_context_manager_now() -> Optional[datetime]:
    if not has_runtime_context():
        return None
    try:
        runtime = get_runtime_context()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to get runtime context for context_manager_now", data={"error": str(exc)})
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


def _check_image_size(display_name: str, size_bytes: int) -> None:
    """Raise ValueError if the image exceeds the configured per-image byte limit."""
    max_image_bytes = get_chunking_max_image_bytes_per_image()
    if max_image_bytes > 0 and size_bytes > max_image_bytes:
        max_image_mb = get_chunking_max_image_mb_per_image()
        raise ValueError(
            f"Image '{display_name}' is too large to attach ({size_bytes} bytes). "
            f"Maximum per image is chunking_max_image_mb_per_image={max_image_mb} MB."
        )


def _resolve_image_prompt(
    *,
    prompt_text: str,
    image_paths: Optional[List[str]],
    image_uploads: Optional[List[UploadedImageAttachment]],
    vault_path: str,
) -> tuple[PromptInput, str, int]:
    """Build prompt payload and history-safe text from optional image attachments."""
    if not image_paths and not image_uploads:
        return prompt_text, prompt_text, 0

    vault_root = Path(vault_path).resolve()
    prompt_content: List[UserContent] = [prompt_text]
    history_lines: List[str] = []
    seen_paths: set[str] = set()

    for raw_path in image_paths or []:
        candidate = (raw_path or "").strip()
        if not candidate:
            continue

        image_path = Path(candidate)
        if not image_path.is_absolute():
            image_path = vault_root / image_path
        resolved_path = image_path.resolve()

        if resolved_path != vault_root and vault_root not in resolved_path.parents:
            raise ValueError(
                f"Image path '{candidate}' is outside the vault and cannot be attached."
            )
        if not resolved_path.is_file():
            raise ValueError(f"Image file not found: {candidate}")

        resolved_key = str(resolved_path)
        if resolved_key in seen_paths:
            continue
        seen_paths.add(resolved_key)

        file_content = BinaryContent.from_path(resolved_path)
        if not file_content.is_image:
            raise ValueError(f"File is not an image and cannot be attached: {candidate}")
        _check_image_size(candidate, len(file_content.data))

        prompt_content.append(file_content)
        display_path = resolved_path.relative_to(vault_root).as_posix()
        history_lines.append(f"- {display_path}")

    for upload in image_uploads or []:
        file_content = upload.content
        display_name = (upload.display_name or "").strip() or "uploaded-image"
        if not file_content.is_image:
            raise ValueError(
                f"Uploaded file '{display_name}' is not an image and cannot be attached."
            )
        _check_image_size(display_name, len(file_content.data))
        prompt_content.append(file_content)
        history_lines.append(f"- [upload] {display_name}")

    if len(prompt_content) == 1:
        return prompt_text, prompt_text, 0

    prompt_for_history = "\n".join(
        [
            prompt_text,
            "",
            "[Attached images]",
            *history_lines,
        ]
    )
    return prompt_content, prompt_for_history, len(prompt_content) - 1


def _validate_image_capability(
    model_alias: str,
    image_paths: Optional[List[str]],
    image_uploads: Optional[List[UploadedImageAttachment]],
) -> None:
    """Fail fast if image attachments are requested for a non-vision model."""
    has_uploads = bool(image_uploads)
    if not image_paths and not has_uploads:
        return
    has_paths = any((path or "").strip() for path in (image_paths or []))
    if not has_paths and not has_uploads:
        return
    if model_supports_capability(model_alias, "vision"):
        return
    details = _build_model_capability_details(
        model_alias,
        "vision",
        image_paths=image_paths,
        image_uploads=image_uploads,
    )
    logger.warning("Chat capability mismatch", data=details)
    raise ChatCapabilityError(
        (
            f"Model '{model_alias}' does not declare 'vision' capability in settings.yaml. "
            "Use a vision-capable model or remove image attachments."
        ),
        details=details,
    )


async def _prepare_chat_execution(
    vault_name: str,
    vault_path: str,
    prompt: str,
    image_paths: Optional[List[str]],
    image_uploads: Optional[List[UploadedImageAttachment]],
    session_id: str,
    tools: List[str],
    model: str,
    thinking: ThinkingValue | None = None,
    context_template: Optional[str] = None,
) -> PreparedChatExecution:
    """Perform chat preflight before either sync or streaming execution begins."""
    _validate_image_capability(model, image_paths, image_uploads)
    workspace_path = _CHAT_STORE.get_session_workspace_path(session_id, vault_name)
    base_instructions, tool_instructions, model_instance, tool_functions = _prepare_agent_config(
        vault_name, vault_path, tools, model, thinking
    )

    capabilities = build_chat_capabilities(
        vault_name=vault_name,
        vault_path=vault_path,
        session_id=session_id,
        model_alias=model,
        context_template=context_template,
        now=_resolve_context_manager_now(),
        workspace_path=workspace_path,
        event_sink=_CHAT_STORE,
        tools=tool_functions,
        tool_instructions="",
        history_processor_factory=build_context_manager_history_processor,
    )

    agent = await create_agent(
        model=model_instance,
        capabilities=capabilities,
    )
    for inst in [base_instructions, tool_instructions]:
        if inst:
            agent.instructions(lambda _ctx, text=inst: text)

    message_history = _with_failure_recovery_context(
        _CHAT_STORE.get_history(session_id, vault_name),
        session_id=session_id,
        vault_name=vault_name,
    )
    user_prompt, prompt_for_history, attached_image_count = _resolve_image_prompt(
        prompt_text=prompt,
        image_paths=image_paths,
        image_uploads=image_uploads,
        vault_path=vault_path,
    )
    return PreparedChatExecution(
        agent=agent,
        message_history=message_history,
        prompt_for_history=prompt_for_history,
        user_prompt=user_prompt,
        attached_image_count=attached_image_count,
        model=model,
        tools=list(tools),
        context_template=context_template,
        workspace_path=workspace_path,
    )


def _prepare_agent_config(
    vault_name: str,
    vault_path: str,
    tools: List[str],
    model: str,
    thinking: ThinkingValue | None = None,
) -> tuple:
    """
    Prepare agent configuration (shared between streaming and non-streaming).

    Returns:
        Tuple of (base_instructions, tool_instructions, model_instance, tool_functions)
    """
    base_instructions = REGULAR_CHAT_INSTRUCTIONS

    # Process tools directive to get tool functions
    tool_functions = []
    tool_instructions = ""

    if tools:  # Only process if tools list is not empty
        tools_value = ", ".join(tools)  # Convert list to comma-separated string
        binding = resolve_tool_binding(tools_value, vault_path=vault_path)
        tool_functions = binding.tool_functions
        tool_instructions = binding.tool_instructions

    resolved_thinking = thinking if thinking is not None else get_default_model_thinking()
    model_instance = build_model_instance(model, thinking=resolved_thinking)
    if isinstance(model_instance, ModelExecutionSpec) and model_instance.mode == "skip":
        raise ValueError(
            "Chat execution does not support skip mode model alias 'none'. "
            "Select a concrete model."
        )

    return base_instructions, tool_instructions, model_instance, tool_functions


async def execute_chat_prompt(
    vault_name: str,
    vault_path: str,
    prompt: str,
    image_paths: Optional[List[str]],
    image_uploads: Optional[List[UploadedImageAttachment]],
    session_id: str,
    tools: List[str],
    model: str,
    thinking: ThinkingValue | None = None,
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
    Returns:
        ChatExecutionResult with response and session metadata
    """
    phase = "preflight"
    attached_image_count = 0
    prepared = None
    accepted_user_persisted = False
    initial_workspace_path = _CHAT_STORE.get_session_workspace_path(session_id, vault_name)
    _log_chat_lifecycle(
        "Chat execution started",
        vault_name=vault_name,
        session_id=session_id,
        model=model,
        context_template=context_template,
        workspace_path=initial_workspace_path,
        extra={"thinking": thinking_value_to_label(thinking)},
        tools=tools,
        streaming=False,
        phase=phase,
        prompt_length=len(prompt),
    )
    try:
        prepared = await _prepare_chat_execution(
            vault_name=vault_name,
            vault_path=vault_path,
            prompt=prompt,
            image_paths=image_paths,
            image_uploads=image_uploads,
            session_id=session_id,
            tools=tools,
            model=model,
            thinking=thinking,
            context_template=context_template,
        )
        attached_image_count = prepared.attached_image_count
        _log_chat_lifecycle(
            "Chat preflight completed",
            vault_name=vault_name,
            session_id=session_id,
            model=model,
            tools=tools,
            streaming=False,
            phase=phase,
            prompt_length=len(prompt),
            attached_image_count=attached_image_count,
            context_template=prepared.context_template,
            workspace_path=prepared.workspace_path,
            extra={
                "history_message_count": len(prepared.message_history or []),
                "prompt_for_history_tokens": estimate_token_count(prepared.prompt_for_history),
            },
        )

        phase = "agent_run"
        runtime = get_runtime_context()
        async with runtime.task_coordinator.track_current_task(
            kind=ExecutionTaskKind.CHAT,
            scope=chat_session_scope(session_id),
            source=ExecutionTaskSource.API,
            label=chat_task_label(session_id),
            metadata={
                "vault": vault_name,
                "session_id": session_id,
                "streaming": False,
                "model": model,
                "tools": list(tools),
            },
        ):
            async with chat_session_history_lock(session_id=session_id, vault_name=vault_name):
                _CHAT_STORE.add_messages(session_id, vault_name, [_accepted_user_request(prepared)])
                accepted_user_persisted = True
            session_buffer_store = get_session_buffer_store(session_id)
            run_deps = ChatRunDeps(
                context_manager_now=_resolve_context_manager_now(),
                buffer_store=session_buffer_store,
                buffer_store_registry={"session": session_buffer_store},
                session_id=session_id,
                vault_name=vault_name,
                message_history=list(prepared.message_history or []),
                tools=list(prepared.tools or []),
            )
            result = await prepared.agent.run(
                prepared.user_prompt,
                message_history=prepared.message_history,
                deps=run_deps,
                usage_limits=_chat_usage_limits(),
            )

            phase = "session_persist"
            async with chat_session_history_lock(session_id=session_id, vault_name=vault_name):
                _CHAT_STORE.add_messages(
                    session_id,
                    vault_name,
                    _messages_after_accepted_user_request(result.new_messages()),
                )
                _clear_latest_turn_failure(session_id=session_id, vault_name=vault_name)
        await _try_auto_compact_after_turn(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
        )
        _log_chat_lifecycle(
            "Chat execution completed",
            vault_name=vault_name,
            session_id=session_id,
            model=model,
            tools=tools,
            streaming=False,
            phase=phase,
            prompt_length=len(prompt),
            attached_image_count=attached_image_count,
            context_template=prepared.context_template,
            workspace_path=prepared.workspace_path,
            extra={
                "message_count": len(result.all_messages()),
                "response_length": len(result.output or ""),
            },
        )

        return ChatExecutionResult(
            response=result.output,
            session_id=session_id,
            message_count=len(result.all_messages()),
            history_file=None,
        )
    except asyncio.CancelledError as exc:
        failure_workspace_path = prepared.workspace_path if prepared else initial_workspace_path
        _log_chat_failure(
            "Chat execution cancelled",
            vault_name=vault_name,
            session_id=session_id,
            model=model,
            tools=tools,
            streaming=False,
            phase=phase,
            prompt_length=len(prompt),
            attached_image_count=attached_image_count,
            context_template=prepared.context_template if prepared else context_template,
            workspace_path=failure_workspace_path,
            exc=exc,
        )
        raise
    except UsageLimitExceeded as exc:
        limit_error = _build_chat_usage_limit_error(exc)
        failure_workspace_path = prepared.workspace_path if prepared else initial_workspace_path
        _log_chat_failure(
            f"Chat {_usage_limit_label(limit_error)} exceeded",
            vault_name=vault_name,
            session_id=session_id,
            model=model,
            tools=tools,
            streaming=False,
            phase=phase,
            prompt_length=len(prompt),
            attached_image_count=attached_image_count,
            context_template=prepared.context_template if prepared else context_template,
            workspace_path=failure_workspace_path,
            extra=limit_error.details,
            exc=exc,
        )
        if accepted_user_persisted:
            _record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase=phase,
                streaming=False,
                model=model,
                tools=tools,
            )
        raise limit_error from exc
    except Exception as exc:
        failure_workspace_path = prepared.workspace_path if prepared else initial_workspace_path
        _log_chat_failure(
            "Chat execution failed",
            vault_name=vault_name,
            session_id=session_id,
            model=model,
            tools=tools,
            streaming=False,
            phase=phase,
            prompt_length=len(prompt),
            attached_image_count=attached_image_count,
            context_template=prepared.context_template if prepared else context_template,
            workspace_path=failure_workspace_path,
            exc=exc,
        )
        if accepted_user_persisted:
            _record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase=phase,
                streaming=False,
                model=model,
                tools=tools,
            )
        if isinstance(exc, ContextTemplateExecutionError):
            details = build_context_template_error_details(
                vault_name=vault_name,
                session_id=session_id,
                template_name=exc.template_name,
                phase=exc.phase,
                template_pointer=exc.template_pointer,
            )
            logger.warning(
                "Selected context template failed during chat execution",
                data=details | {"error": str(exc)},
            )
            raise ChatContextTemplateError(str(exc), details=details) from exc
        raise


async def _stream_prepared_chat_prompt(
    *,
    prepared: PreparedChatExecution,
    vault_name: str,
    vault_path: str,
    session_id: str,
) -> AsyncIterator[str]:
    """Stream a preflighted chat execution as SSE events."""
    full_response = ""
    final_result = None
    tool_activity: dict[str, dict[str, Any]] = {}
    session_buffer_store = get_session_buffer_store(session_id)
    run_deps = ChatRunDeps(
        context_manager_now=_resolve_context_manager_now(),
        buffer_store=session_buffer_store,
        buffer_store_registry={"session": session_buffer_store},
        session_id=session_id,
        vault_name=vault_name,
        message_history=list(prepared.message_history or []),
        tools=list(prepared.tools or []),
    )

    runtime = get_runtime_context()
    async with runtime.task_coordinator.track_current_task(
        kind=ExecutionTaskKind.CHAT,
        scope=chat_session_scope(session_id),
        source=ExecutionTaskSource.API,
        label=chat_task_label(session_id),
        metadata={
            "vault": vault_name,
            "session_id": session_id,
            "streaming": True,
            "model": prepared.model,
            "tools": list(prepared.tools),
        },
    ) as task:
        async with chat_session_history_lock(session_id=session_id, vault_name=vault_name):
            _CHAT_STORE.add_messages(session_id, vault_name, [_accepted_user_request(prepared)])

        _log_chat_lifecycle(
            "Streaming chat execution started",
            vault_name=vault_name,
            session_id=session_id,
            model=prepared.model,
            tools=prepared.tools,
            streaming=True,
            phase="agent_stream",
            prompt_length=len(prepared.prompt_for_history),
            attached_image_count=prepared.attached_image_count,
            context_template=prepared.context_template,
            workspace_path=prepared.workspace_path,
            extra={
                "history_message_count": len(prepared.message_history or []),
                "prompt_for_history_tokens": estimate_token_count(prepared.prompt_for_history),
                "task_id": task.task_id,
            },
        )

        try:
            async for event in prepared.agent.run_stream_events(
                prepared.user_prompt,
                message_history=prepared.message_history,
                deps=run_deps,
                usage_limits=_chat_usage_limits(),
            ):
                if isinstance(event, PartStartEvent):
                    if isinstance(event.part, TextPart) and event.part.content:
                        delta_text = event.part.content
                        full_response += delta_text
                        chunk = {
                            "event": "delta",
                            "choices": [{
                                "delta": {"content": delta_text},
                                "index": 0,
                                "finish_reason": None,
                            }],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"

                elif isinstance(event, PartDeltaEvent):
                    if isinstance(event.delta, TextPartDelta):
                        delta_text = event.delta.content_delta
                        full_response += delta_text
                        chunk = {
                            "event": "delta",
                            "choices": [{
                                "delta": {"content": delta_text},
                                "index": 0,
                                "finish_reason": None,
                            }],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"

                elif isinstance(event, FunctionToolCallEvent):
                    tool_id = event.tool_call_id
                    tool_part = getattr(event, "part", None)
                    tool_name = getattr(tool_part, "tool_name", "tool")
                    tool_args = None
                    if tool_part is not None:
                        try:
                            tool_args = tool_part.args_as_json_str()
                        except Exception as exc:  # noqa: BLE001 - defensive: upstream variations
                            logger.debug("args_as_json_str failed; using raw args", data={"error": str(exc)})
                            tool_args = tool_part.args
                    tool_activity[tool_id] = {
                        "tool_name": tool_name,
                        "status": "running",
                    }
                    metadata_chunk = {
                        "event": "tool_call_started",
                        "tool_call_id": tool_id,
                        "tool_name": tool_name,
                        "arguments": _normalize_tool_args(tool_args),
                    }
                    if tool_name == "code_execution":
                        metadata_chunk["arguments_detail"] = _normalize_tool_detail(tool_args)
                    logger.set_sinks(["validation"]).info(
                        "Streaming tool call started",
                        data={
                            "event": "chat_tool_call_started",
                            "vault_name": vault_name,
                            "session_id": session_id,
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "arguments_length": len(tool_args or ""),
                            "memory_rss_bytes": _get_process_rss_bytes(),
                        },
                    )
                    yield f"data: {json.dumps(metadata_chunk)}\n\n"

                elif isinstance(event, FunctionToolResultEvent):
                    tool_id = event.tool_call_id
                    result_part = getattr(event, "result", None)
                    tool_name = getattr(result_part, "tool_name", "tool")
                    result_content = None
                    if result_part is not None:
                        try:
                            result_content = result_part.model_response_str()
                        except Exception as exc:  # noqa: BLE001 - defensive fallback
                            logger.debug("model_response_str failed; using raw content", data={"error": str(exc)})
                            result_content = getattr(result_part, "content", None)
                    tool_activity[tool_id] = {
                        "tool_name": tool_name,
                        "status": "completed",
                    }
                    metadata_chunk = {
                        "event": "tool_call_finished",
                        "tool_call_id": tool_id,
                        "tool_name": tool_name,
                        "result": _normalize_tool_result(result_content),
                    }
                    if tool_name == "code_execution":
                        metadata_chunk["result_detail"] = _normalize_tool_detail(result_content)
                    result_text = tool_result_as_text(result_content)
                    logger.set_sinks(["validation"]).info(
                        "Streaming tool call finished",
                        data={
                            "event": "chat_tool_call_finished",
                            "vault_name": vault_name,
                            "session_id": session_id,
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "result_length": len(result_text),
                            "result_token_estimate": estimate_token_count(result_text) if result_text else 0,
                            "memory_rss_bytes": _get_process_rss_bytes(),
                        },
                    )
                    yield f"data: {json.dumps(metadata_chunk)}\n\n"

                elif isinstance(event, AgentRunResultEvent):
                    final_result = event.result

            final_chunk = {
                "event": "done",
                "choices": [{
                    "delta": {},
                    "index": 0,
                    "finish_reason": "stop",
                }],
                "tool_summary": tool_activity,
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"

        except asyncio.CancelledError as exc:
            await runtime.task_coordinator.mark_cancelled(task.task_id, reason="cancelled")
            _log_chat_failure(
                "Streaming chat execution cancelled",
                vault_name=vault_name,
                session_id=session_id,
                model=prepared.model,
                tools=prepared.tools,
                streaming=True,
                phase="agent_stream",
                prompt_length=len(prepared.prompt_for_history),
                attached_image_count=prepared.attached_image_count,
                context_template=prepared.context_template,
                workspace_path=prepared.workspace_path,
                extra=_summarize_tool_activity(tool_activity),
                exc=exc,
            )
            cancel_chunk = {
                "event": "cancelled",
                "choices": [{
                    "delta": {},
                    "index": 0,
                    "finish_reason": "cancelled",
                }],
            }
            yield f"data: {json.dumps(cancel_chunk)}\n\n"
            return
        except ChatCapabilityError as exc:
            logger.warning("Streaming capability mismatch", data=exc.details)
            _record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            error_chunk = {
                "event": "error",
                "choices": [{
                    "delta": {"content": f"\n\n❌ Error: {str(exc)}"},
                    "index": 0,
                    "finish_reason": "error",
                }],
                "details": exc.details,
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            return
        except ContextTemplateExecutionError as exc:
            details = build_context_template_error_details(
                vault_name=vault_name,
                session_id=session_id,
                template_name=exc.template_name,
                phase=exc.phase,
                template_pointer=exc.template_pointer,
            )
            logger.warning("Streaming context template execution failure", data=details | {"error": str(exc)})
            _record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            error_chunk = {
                "event": "error",
                "choices": [{
                    "delta": {"content": f"\n\nTemplate error: {str(exc)}"},
                    "index": 0,
                    "finish_reason": "error",
                }],
                "details": details,
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            return
        except ChatContextTemplateError as exc:
            logger.warning("Streaming context template failure", data=exc.details)
            _record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            error_chunk = {
                "event": "error",
                "choices": [{
                    "delta": {"content": f"\n\nTemplate error: {str(exc)}"},
                    "index": 0,
                    "finish_reason": "error",
                }],
                "details": exc.details,
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            return
        except UsageLimitExceeded as exc:
            limit_error = _build_chat_usage_limit_error(exc)
            _log_chat_failure(
                f"Streaming chat {_usage_limit_label(limit_error)} exceeded",
                vault_name=vault_name,
                session_id=session_id,
                model=prepared.model,
                tools=prepared.tools,
                streaming=True,
                phase="agent_stream",
                prompt_length=len(prepared.prompt_for_history),
                attached_image_count=prepared.attached_image_count,
                context_template=prepared.context_template,
                workspace_path=prepared.workspace_path,
                extra={**_summarize_tool_activity(tool_activity), **limit_error.details},
                exc=exc,
            )
            _record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            error_chunk = {
                "event": "error",
                "choices": [{
                    "delta": {"content": f"\n\n{_usage_limit_display_label(limit_error)} reached: {str(limit_error)}"},
                    "index": 0,
                    "finish_reason": "error",
                }],
                "details": limit_error.details,
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            return
        except Exception as e:
            classification = classify_exception(e, phase="agent_stream")
            _log_chat_failure(
                "Streaming chat execution failed",
                vault_name=vault_name,
                session_id=session_id,
                model=prepared.model,
                tools=prepared.tools,
                streaming=True,
                phase="agent_stream",
                prompt_length=len(prepared.prompt_for_history),
                attached_image_count=prepared.attached_image_count,
                context_template=prepared.context_template,
                workspace_path=prepared.workspace_path,
                extra=_summarize_tool_activity(tool_activity),
                exc=e,
            )
            _record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=e,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            error_chunk = {
                "event": "error",
                "choices": [{
                    "delta": {"content": "\n\n❌ Error: An unexpected error occurred"},
                    "index": 0,
                    "finish_reason": "error",
                }],
                "details": classification.to_metadata(),
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            raise

        if final_result:
            async with chat_session_history_lock(session_id=session_id, vault_name=vault_name):
                _CHAT_STORE.add_messages(
                    session_id,
                    vault_name,
                    _messages_after_accepted_user_request(final_result.new_messages()),
                )
                _clear_latest_turn_failure(session_id=session_id, vault_name=vault_name)
            _log_chat_lifecycle(
                "Streaming chat execution completed",
                vault_name=vault_name,
                session_id=session_id,
                model=prepared.model,
                tools=prepared.tools,
                streaming=True,
                phase="session_persist",
                prompt_length=len(prepared.prompt_for_history),
                attached_image_count=prepared.attached_image_count,
                context_template=prepared.context_template,
                workspace_path=prepared.workspace_path,
                extra={
                    **_summarize_tool_activity(tool_activity),
                    "response_length": len(full_response),
                },
            )

    if final_result:
        await _try_auto_compact_after_turn(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
        )


async def execute_chat_prompt_stream(
    vault_name: str,
    vault_path: str,
    prompt: str,
    image_paths: Optional[List[str]],
    image_uploads: Optional[List[UploadedImageAttachment]],
    session_id: str,
    tools: List[str],
    model: str,
    thinking: ThinkingValue | None = None,
    context_template: Optional[str] = None,
) -> AsyncIterator[str]:
    """Preflight streaming chat execution and yield SSE chunks."""
    try:
        prepared = await _prepare_chat_execution(
            vault_name=vault_name,
            vault_path=vault_path,
            prompt=prompt,
            image_paths=image_paths,
            image_uploads=image_uploads,
            session_id=session_id,
            tools=tools,
            model=model,
            thinking=thinking,
            context_template=context_template,
        )
    except Exception as exc:
        _log_chat_failure(
            "Streaming chat preflight failed",
            vault_name=vault_name,
            session_id=session_id,
            model=model,
            tools=tools,
            streaming=True,
            phase="preflight",
            prompt_length=len(prompt),
            context_template=context_template,
            workspace_path=_CHAT_STORE.get_session_workspace_path(session_id, vault_name),
            exc=exc,
        )
        if isinstance(exc, ChatContextTemplateError):
            error_chunk = {
                "event": "error",
                "choices": [{
                    "delta": {"content": f"\n\nTemplate error: {str(exc)}"},
                    "index": 0,
                    "finish_reason": "error"
                }],
                "details": exc.details,
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            return
        raise
    async for chunk in _stream_prepared_chat_prompt(
        prepared=prepared,
        vault_name=vault_name,
        vault_path=vault_path,
        session_id=session_id,
    ):
        yield chunk
