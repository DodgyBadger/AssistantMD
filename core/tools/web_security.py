"""Shared web-tool result security formatting."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ToolReturn

from core.constants import (
    UNTRUSTED_WEB_DATA_BEGIN,
    UNTRUSTED_WEB_DATA_END,
    WEB_SOURCE_TOOL_NAMES,
)

_HOST_GENERATED_PREFIXES = (
    "browser error:",
    "duckduckgo search error:",
    "no content could be crawled from:",
    "no content could be extracted from:",
    "no search results found for:",
    "tavily api error:",
    "tavily crawl error:",
    "tavily extract error:",
    "tavily search error:",
)


def wrap_untrusted_web_data(content: str) -> str:
    """Wrap successful web-derived tool output with an explicit trust boundary."""
    text = str(content or "").strip()
    if not text:
        return text
    return f"{UNTRUSTED_WEB_DATA_BEGIN}\n\n{text}\n\n{UNTRUSTED_WEB_DATA_END}"


def wrap_web_tool_result(tool_name: str, result: Any) -> Any:
    """Wrap successful web-derived results from configured web tools."""
    if tool_name not in WEB_SOURCE_TOOL_NAMES:
        return result

    if isinstance(result, ToolReturn):
        if result.content is not None:
            return result
        wrapped = _wrap_if_web_content(result.return_value)
        if wrapped == result.return_value:
            return result
        return ToolReturn(
            return_value=wrapped,
            content=result.content,
            metadata=result.metadata,
        )

    if isinstance(result, str):
        return _wrap_if_web_content(result)

    return result


def _wrap_if_web_content(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    normalized = text.lower()
    if normalized.startswith(UNTRUSTED_WEB_DATA_BEGIN.lower()):
        return value
    if any(normalized.startswith(prefix) for prefix in _HOST_GENERATED_PREFIXES):
        return value
    return wrap_untrusted_web_data(value)
