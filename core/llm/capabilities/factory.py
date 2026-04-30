"""Capability composition for AssistantMD agent runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from core.llm.capabilities.assistant_tools import build_assistant_tools_capabilities
from core.llm.capabilities.chat_context import build_chat_context_capability
from core.llm.capabilities.chat_tool_output_cache import (
    ToolEventSink,
    build_chat_tool_output_cache_capability,
)


def build_chat_capabilities(
    *,
    vault_name: str,
    vault_path: str,
    session_id: str,
    model_alias: str,
    context_template: str | None,
    now: datetime | None,
    event_sink: ToolEventSink,
    tools: list[object] | None = None,
    tool_instructions: str = "",
    history_processor_factory: Callable[..., Any] | None = None,
) -> list[Any]:
    """Compose capabilities for normal and streaming chat runs."""
    capabilities: list[Any] = []

    context_capability = build_chat_context_capability(
        vault_name=vault_name,
        vault_path=vault_path,
        session_id=session_id,
        model_alias=model_alias,
        context_template=context_template,
        **(
            {"history_processor_factory": history_processor_factory}
            if history_processor_factory is not None
            else {}
        ),
    )
    if context_capability is not None:
        capabilities.append(context_capability)

    capabilities.extend(
        build_assistant_tools_capabilities(
            tools=list(tools or []),
            instructions=tool_instructions,
        )
    )

    capabilities.append(
        build_chat_tool_output_cache_capability(
            vault_name=vault_name,
            session_id=session_id,
            now=now,
            event_sink=event_sink,
        )
    )

    return capabilities
