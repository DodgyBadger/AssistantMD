"""Utilities for working with pydantic_ai ModelMessage histories."""

from __future__ import annotations

from typing import List, Optional

from pydantic_ai.messages import (
    BuiltinToolReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


def _model_request_has_user_prompt(message: ModelRequest) -> bool:
    parts = getattr(message, "parts", None) or ()
    for part in parts:
        if isinstance(part, UserPromptPart):
            return True
    return False


def run_slice(msgs: List[ModelMessage], runs_to_take: int) -> List[ModelMessage]:
    run_ids: List[str] = []
    for m in msgs:
        rid = getattr(m, "run_id", None)
        if rid:
            if not run_ids or run_ids[-1] != rid:
                run_ids.append(rid)
    if run_ids:
        if runs_to_take == 0:
            return []
        take_runs = runs_to_take if runs_to_take > 0 else len(run_ids)
        selected_run_ids = set(run_ids[-take_runs:])
        start_idx = 0
        for idx, m in enumerate(msgs):
            if getattr(m, "run_id", None) in selected_run_ids:
                start_idx = idx
                break
        return msgs[start_idx:]
    # Fallback: slice from last user message to end (user→assistant→tools)
    last_user_idx = None
    for idx in range(len(msgs) - 1, -1, -1):
        m = msgs[idx]
        role = getattr(m, "role", None)
        if role and role.lower() == "user":
            last_user_idx = idx
            break
        if isinstance(m, ModelRequest) and _model_request_has_user_prompt(m):
            last_user_idx = idx
            break
    if last_user_idx is not None:
        return msgs[last_user_idx:]
    return msgs


def extract_role_and_text(msg: ModelMessage) -> tuple[str, str]:
    # Normalize role names across message types
    if isinstance(msg, ModelRequest):
        role = "user"
    elif isinstance(msg, ModelResponse):
        role = "assistant"
    else:
        role = getattr(msg, "role", None) or msg.__class__.__name__.lower()

    parts = getattr(msg, "parts", None)
    if parts:
        has_system_part = False
        rendered_parts: List[str] = []
        for part in parts:
            if isinstance(part, (UserPromptPart, TextPart)):
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(part_content)
            elif isinstance(part, SystemPromptPart):
                has_system_part = True
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(part_content)
            elif isinstance(part, (ToolReturnPart, BuiltinToolReturnPart)):
                tool_name = getattr(part, "tool_name", None) or getattr(part, "tool_call_id", None) or "tool"
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(f"[{tool_name}] {part_content}")
            elif isinstance(part, ToolCallPart):
                tool_name = getattr(part, "tool_name", None) or getattr(part, "tool_call_id", None) or "tool"
                rendered_parts.append(f"[{tool_name}] (tool call)")
        if rendered_parts:
            if has_system_part and role == "user":
                return "system", "\n".join(rendered_parts)
            return role, "\n".join(rendered_parts)

    # Try direct content if no parts were rendered
    content = getattr(msg, "content", None)
    if isinstance(content, str) and content:
        return role, content

    return role, ""
