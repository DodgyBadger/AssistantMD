"""
Chat execution logic for dynamic prompt execution.

Handles stateful/stateless chat with user-selected tools and models.
Persists canonical chat history in the structured chat store.
"""

import json
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, AsyncIterator, Any, Sequence
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, TextPart, ToolReturn, UserPromptPart
from pydantic_ai import (
    BinaryContent,
    PartStartEvent, PartDeltaEvent, AgentRunResultEvent,
    TextPartDelta, FunctionToolCallEvent, FunctionToolResultEvent
)
from pydantic_ai.messages import UserContent

from core.llm.agents import create_agent
from core.chat.chat_store import ChatStore
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
from core.settings import (
    get_auto_cache_max_tokens,
    get_chunking_max_image_bytes_per_image,
    get_chunking_max_image_mb_per_image,
    get_default_model_thinking,
)
from core.settings.store import get_general_settings
from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context, has_runtime_context
from core.runtime.buffers import BufferStore, get_session_buffer_store
from core.authoring.cache import purge_expired_cache_artifacts, upsert_cache_artifact
from core.tools.utils import estimate_token_count


logger = UnifiedLogger(tag="chat-executor")


PromptInput = str | Sequence[UserContent]


_CHAT_STORE = ChatStore()


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


@dataclass
class PreparedChatExecution:
    """Preflighted chat execution state safe to reuse across sync and streaming paths."""

    agent: Any
    message_history: Optional[List[ModelMessage]]
    prompt_for_history: str
    user_prompt: PromptInput
    attached_image_count: int
    model: str
    tools: List[str]


def _build_user_prompt_message(prompt_text: str) -> ModelRequest:
    """Return a canonical stored chat message for the current user prompt."""
    return ModelRequest(parts=[UserPromptPart(content=prompt_text)])


def _serialize_exception(exc: Exception) -> dict[str, Any]:
    """Return stable exception details for activity-log diagnostics."""
    return {
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).strip(),
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
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Emit structured lifecycle logs for chat session execution."""
    payload: dict[str, Any] = {
        "vault_name": vault_name,
        "session_id": session_id,
        "streaming": streaming,
        "phase": phase,
    }
    if model is not None:
        payload["model"] = model
    if tools is not None:
        payload["tools"] = list(tools)
        payload["tools_count"] = len(tools)
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
    extra: Optional[dict[str, Any]] = None,
    exc: Exception,
) -> None:
    """Emit structured failure logs for chat session execution."""
    payload = _serialize_exception(exc)
    if extra:
        payload.update(extra)
    rss_bytes = _get_process_rss_bytes()
    if rss_bytes is not None:
        payload["memory_rss_bytes"] = rss_bytes
    logger.error(
        message,
        data={
            "vault_name": vault_name,
            "session_id": session_id,
            "streaming": streaming,
            "phase": phase,
            "model": model,
            "tools": list(tools or []),
            "tools_count": len(tools or []),
            "prompt_length": prompt_length,
            "attached_image_count": attached_image_count,
            **payload,
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


def _tool_result_has_multimodal_payload(result: Any) -> bool:
    if not isinstance(result, ToolReturn):
        return False
    content = result.content
    if content is None or isinstance(content, str):
        return False
    return True


def _tool_result_as_text(result: Any) -> str:
    if isinstance(result, ToolReturn):
        return str(result.return_value or "")
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


def _chat_cache_owner_id(*, vault_name: str, session_id: str) -> str:
    return f"{vault_name}/chat/{session_id}"


def _chat_cache_ref(*, tool_name: str, tool_call_id: str) -> str:
    safe_tool_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", tool_name).strip("-") or "tool"
    safe_call_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", tool_call_id).strip("-") or "call"
    return f"tool/{safe_tool_name}/{safe_call_id}"


def _should_preserve_vault_backed_tool_result(tool_name: str, args: dict[str, Any]) -> bool:
    if tool_name != "file_ops_safe":
        return False
    operation = str(args.get("operation") or "").strip().lower()
    return operation == "read"


def _build_large_vault_read_notice(*, tool_name: str, args: dict[str, Any], token_count: int, token_limit: int) -> str:
    target = str(args.get("target") or "").strip() or "<unknown>"
    return (
        f"Tool '{tool_name}' produced a large vault-backed file read for '{target}' "
        f"({token_count} estimated tokens > {token_limit}). The content was not inlined or cached. "
        "Explore the underlying file incrementally with targeted reads or switch to constrained-Python "
        "exploration against the file path."
    )


def _build_cached_tool_overflow_notice(
    *,
    tool_name: str,
    cache_ref: str,
    token_count: int,
    token_limit: int,
    preview: str,
) -> str:
    return (
        f"Tool '{tool_name}' produced a large result ({token_count} estimated tokens > {token_limit}) "
        f"and it was stored in cache ref '{cache_ref}'. Preview:\n\n{preview}\n\n"
        "Do not request the full content inline. Switch to `code_execution_local` and use "
        f"`await read_cache(ref={cache_ref!r})` to inspect the cached artifact by ref."
    )


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


def _normalize_context_template_selection(context_template: Optional[str]) -> Optional[str]:
    """Return a selected template name or None for unmanaged chat."""
    if context_template is None:
        return None
    normalized = str(context_template).strip()
    return normalized or None


def _get_global_default_template() -> Optional[str]:
    try:
        entry = get_general_settings().get("default_context_template")
        if entry and entry.value:
            return str(entry.value).strip() or None
    except Exception:
        pass
    return None


def _build_context_template_candidates(
    context_template: Optional[str],
) -> list[str]:
    """Resolve the chat context-template fallback chain."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _append(value: Optional[str]) -> None:
        normalized = _normalize_context_template_selection(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    _append(context_template)
    _append(_get_global_default_template())
    _append("default.md")
    return candidates


def _build_context_template_error_details(
    *,
    vault_name: str,
    session_id: str,
    template_name: str,
    phase: str,
    template_pointer: str,
) -> dict[str, Any]:
    return {
        "vault_name": vault_name,
        "session_id": session_id,
        "template_name": template_name,
        "phase": phase,
        "template_pointer": template_pointer,
    }


def _build_chat_tool_overflow_capability(
    *,
    vault_name: str,
    session_id: str,
    now: datetime | None,
) -> Any | None:
    from pydantic_ai.capabilities import Hooks

    hooks = Hooks()

    @hooks.on.before_tool_execute
    async def persist_tool_call(ctx, *, call, tool_def, args):
        del ctx, tool_def
        _CHAT_STORE.add_tool_event(
            session_id=session_id,
            vault_name=vault_name,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            event_type="call",
            args=args if isinstance(args, dict) else None,
        )
        return args

    @hooks.on.after_tool_execute
    async def cache_oversized_tool_output(ctx, *, call, tool_def, args, result):
        del ctx, tool_def
        token_limit = get_auto_cache_max_tokens()

        if _tool_result_has_multimodal_payload(result):
            _CHAT_STORE.add_tool_event(
                session_id=session_id,
                vault_name=vault_name,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                event_type="result",
                result_text="[multimodal tool result]",
                result_metadata={"multimodal": True},
            )
            return result

        text = _tool_result_as_text(result)
        if not text:
            _CHAT_STORE.add_tool_event(
                session_id=session_id,
                vault_name=vault_name,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                event_type="result",
            )
            return result

        token_count = estimate_token_count(text)
        if token_limit <= 0 or token_count <= token_limit:
            _CHAT_STORE.add_tool_event(
                session_id=session_id,
                vault_name=vault_name,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                event_type="result",
                result_text=text,
                result_metadata={"token_count": token_count},
            )
            return result

        if _should_preserve_vault_backed_tool_result(call.tool_name, args):
            logger.info(
                "Chat oversized vault-backed tool result left inline as file ref guidance",
                data={
                    "vault_name": vault_name,
                    "session_id": session_id,
                    "tool_name": call.tool_name,
                    "tool_call_id": call.tool_call_id,
                    "token_count": token_count,
                    "token_limit": token_limit,
                },
            )
            notice = _build_large_vault_read_notice(
                tool_name=call.tool_name,
                args=args,
                token_count=token_count,
                token_limit=token_limit,
            )
            _CHAT_STORE.add_tool_event(
                session_id=session_id,
                vault_name=vault_name,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                event_type="result",
                result_text=notice,
                result_metadata={
                    "token_count": token_count,
                    "token_limit": token_limit,
                    "vault_backed_file_ref": True,
                },
            )
            return notice

        reference_time = now or datetime.now()
        cache_ref = _chat_cache_ref(tool_name=call.tool_name, tool_call_id=call.tool_call_id)
        purge_expired_cache_artifacts(now=reference_time)
        upsert_cache_artifact(
            owner_id=_chat_cache_owner_id(vault_name=vault_name, session_id=session_id),
            session_key=session_id,
            artifact_ref=cache_ref,
            cache_mode="session",
            ttl_seconds=None,
            raw_content=text,
            metadata={
                "origin": "chat_tool_overflow",
                "tool_name": call.tool_name,
                "tool_call_id": call.tool_call_id,
                "token_count": token_count,
            },
            origin="chat_tool_overflow",
            now=reference_time,
            week_start_day=0,
        )
        preview_limit = 1200
        preview = text[:preview_limit]
        if len(text) > preview_limit:
            preview += "\n… [truncated]"

        logger.info(
            "Chat oversized tool result stored in cache",
            data={
                "vault_name": vault_name,
                "session_id": session_id,
                "tool_name": call.tool_name,
                "tool_call_id": call.tool_call_id,
                "cache_ref": cache_ref,
                "token_count": token_count,
                "token_limit": token_limit,
            },
        )
        _CHAT_STORE.add_tool_event(
            session_id=session_id,
            vault_name=vault_name,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            event_type="overflow_cached",
            args=args if isinstance(args, dict) else None,
            result_text=preview,
            result_metadata={
                "token_count": token_count,
                "token_limit": token_limit,
            },
            artifact_ref=cache_ref,
        )
        return _build_cached_tool_overflow_notice(
            tool_name=call.tool_name,
            cache_ref=cache_ref,
            token_count=token_count,
            token_limit=token_limit,
            preview=preview,
        )

    return hooks


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
    base_instructions, tool_instructions, model_instance, tool_functions = _prepare_agent_config(
        vault_name, vault_path, tools, model, thinking
    )

    template_candidates = _build_context_template_candidates(context_template)
    history_processors = []
    if template_candidates:
        loaded = False
        for candidate in template_candidates:
            try:
                history_processors.append(
                    build_context_manager_history_processor(
                        session_id=session_id,
                        vault_name=vault_name,
                        vault_path=vault_path,
                        model_alias=model,
                        template_name=candidate,
                    )
                )
                loaded = True
                break
            except ContextTemplateExecutionError as exc:
                logger.warning(
                    "Context template failed, trying next in fallback chain",
                    data=_build_context_template_error_details(
                        vault_name=vault_name,
                        session_id=session_id,
                        template_name=exc.template_name,
                        phase=exc.phase,
                        template_pointer=exc.template_pointer,
                    ) | {"error": str(exc), "candidate": candidate},
                )
        if not loaded:
            logger.warning(
                "All context template candidates failed; proceeding without context template",
                data={"vault_name": vault_name, "session_id": session_id, "tried": template_candidates},
            )
    overflow_capability = _build_chat_tool_overflow_capability(
        vault_name=vault_name,
        session_id=session_id,
        now=_resolve_context_manager_now(),
    )

    agent = await create_agent(
        model=model_instance,
        tools=tool_functions if tool_functions else None,
        history_processors=history_processors,
        capabilities=[overflow_capability] if overflow_capability is not None else None,
    )
    for inst in [base_instructions, tool_instructions]:
        if inst:
            agent.instructions(lambda _ctx, text=inst: text)

    message_history = _CHAT_STORE.get_history(session_id, vault_name)
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
    _log_chat_lifecycle(
        "Chat execution started",
        vault_name=vault_name,
        session_id=session_id,
        model=model,
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
            extra={
                "history_message_count": len(prepared.message_history or []),
                "prompt_for_history_tokens": estimate_token_count(prepared.prompt_for_history),
            },
        )

        phase = "agent_run"
        _CHAT_STORE.add_messages(
            session_id,
            vault_name,
            [_build_user_prompt_message(prepared.prompt_for_history)],
        )
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
        )

        phase = "session_persist"
        _CHAT_STORE.add_messages(session_id, vault_name, result.new_messages())
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
    except Exception as exc:
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
            exc=exc,
        )
        if isinstance(exc, ContextTemplateExecutionError):
            details = _build_context_template_error_details(
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
        extra={
            "history_message_count": len(prepared.message_history or []),
            "prompt_for_history_tokens": estimate_token_count(prepared.prompt_for_history),
        },
    )

    try:
        # Use run_stream_events() to properly handle tool calls
        # This runs the agent graph to completion and streams all events
        async for event in prepared.agent.run_stream_events(
            prepared.user_prompt,
            message_history=prepared.message_history,
            deps=run_deps,
        ):
            if isinstance(event, PartStartEvent):
                # Initial visible assistant text part
                if isinstance(event.part, TextPart) and event.part.content:
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
                    "status": "running"
                }
                metadata_chunk = {
                    "event": "tool_call_started",
                    "tool_call_id": tool_id,
                    "tool_name": tool_name,
                    "arguments": _normalize_tool_args(tool_args)
                }
                logger.info(
                    "Streaming tool call started",
                    data={
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
                # Tool returned a result
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
                    "status": "completed"
                }
                metadata_chunk = {
                    "event": "tool_call_finished",
                    "tool_call_id": tool_id,
                    "tool_name": tool_name,
                    "result": _normalize_tool_result(result_content)
                }
                result_text = _tool_result_as_text(result_content)
                logger.info(
                    "Streaming tool call finished",
                    data={
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

    except ChatCapabilityError as exc:
        logger.warning("Streaming capability mismatch", data=exc.details)
        error_chunk = {
            "event": "error",
            "choices": [{
                "delta": {"content": f"\n\n❌ Error: {str(exc)}"},
                "index": 0,
                "finish_reason": "error"
            }],
            "details": exc.details,
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        return
    except ContextTemplateExecutionError as exc:
        details = _build_context_template_error_details(
            vault_name=vault_name,
            session_id=session_id,
            template_name=exc.template_name,
            phase=exc.phase,
            template_pointer=exc.template_pointer,
        )
        logger.warning("Streaming context template execution failure", data=details | {"error": str(exc)})
        error_chunk = {
            "event": "error",
            "choices": [{
                "delta": {"content": f"\n\nTemplate error: {str(exc)}"},
                "index": 0,
                "finish_reason": "error"
            }],
            "details": details,
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        return
    except ChatContextTemplateError as exc:
        logger.warning("Streaming context template failure", data=exc.details)
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
    except Exception as e:
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
            extra={"tool_activity": tool_activity},
            exc=e,
        )
        error_chunk = {
            "event": "error",
            "choices": [{
                "delta": {"content": "\n\n❌ Error: An unexpected error occurred"},
                "index": 0,
                "finish_reason": "error"
            }]
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        raise

    if final_result:
        _CHAT_STORE.add_messages(session_id, vault_name, final_result.new_messages())
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
            extra={
                "tool_activity": tool_activity,
                "response_length": len(full_response),
            },
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
    _CHAT_STORE.add_messages(
        session_id,
        vault_name,
        [_build_user_prompt_message(prepared.prompt_for_history)],
    )
    async for chunk in _stream_prepared_chat_prompt(
        prepared=prepared,
        vault_name=vault_name,
        vault_path=vault_path,
        session_id=session_id,
    ):
        yield chunk
