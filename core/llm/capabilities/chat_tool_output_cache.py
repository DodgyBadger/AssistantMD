"""Chat tool-result event persistence and oversized output cache capability."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Protocol

from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ToolReturn

from core.authoring.cache import purge_expired_cache_artifacts, upsert_cache_artifact
from core.logger import UnifiedLogger
from core.settings import get_auto_cache_max_tokens
from core.tools.utils import estimate_token_count


logger = UnifiedLogger(tag="chat-executor")


class ToolEventSink(Protocol):
    """Minimal store interface needed by chat tool output cache hooks."""

    def add_tool_event(
        self,
        session_id: str,
        vault_name: str,
        tool_call_id: str,
        tool_name: str,
        event_type: str,
        *,
        args: dict[str, Any] | None = None,
        result_text: str | None = None,
        result_metadata: dict[str, Any] | None = None,
        artifact_ref: str | None = None,
    ) -> None:
        """Persist one chat tool event."""


def build_chat_tool_output_cache_capability(
    *,
    vault_name: str,
    session_id: str,
    now: datetime | None,
    event_sink: ToolEventSink,
) -> Hooks:
    """Build hooks for chat tool events and oversized result cache routing."""
    hooks = Hooks()

    @hooks.on.before_tool_execute
    async def persist_tool_call(ctx: Any, *, call: Any, tool_def: Any, args: Any) -> Any:
        del ctx, tool_def
        event_sink.add_tool_event(
            session_id=session_id,
            vault_name=vault_name,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            event_type="call",
            args=args if isinstance(args, dict) else None,
        )
        return args

    @hooks.on.after_tool_execute
    async def cache_oversized_tool_output(
        ctx: Any,
        *,
        call: Any,
        tool_def: Any,
        args: Any,
        result: Any,
    ) -> Any:
        del ctx, tool_def
        token_limit = get_auto_cache_max_tokens()

        if _tool_result_has_multimodal_payload(result):
            event_sink.add_tool_event(
                session_id=session_id,
                vault_name=vault_name,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                event_type="result",
                result_text="[multimodal tool result]",
                result_metadata={"multimodal": True},
            )
            return result

        text = tool_result_as_text(result)
        if not text:
            event_sink.add_tool_event(
                session_id=session_id,
                vault_name=vault_name,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                event_type="result",
            )
            return result

        token_count = estimate_token_count(text)
        if token_limit <= 0 or token_count <= token_limit:
            event_sink.add_tool_event(
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
            event_sink.add_tool_event(
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
        cache_ref = _chat_cache_ref(
            tool_name=call.tool_name,
            tool_call_id=call.tool_call_id,
        )
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
        event_sink.add_tool_event(
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


def _tool_result_has_multimodal_payload(result: Any) -> bool:
    if not isinstance(result, ToolReturn):
        return False
    content = result.content
    if content is None or isinstance(content, str):
        return False
    return True


def tool_result_as_text(result: Any) -> str:
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


def _should_preserve_vault_backed_tool_result(
    tool_name: str,
    args: dict[str, Any],
) -> bool:
    if tool_name != "file_ops_safe":
        return False
    operation = str(args.get("operation") or "").strip().lower()
    return operation == "read"


def _build_large_vault_read_notice(
    *,
    tool_name: str,
    args: dict[str, Any],
    token_count: int,
    token_limit: int,
) -> str:
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
        "Do not request the full content inline. Switch to `code_execution` and use "
        f"`await read_cache(ref={cache_ref!r})` to inspect the cached artifact by ref."
    )
