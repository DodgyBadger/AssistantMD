"""Shared formatting and failure handling for stable web capability tools."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pydantic_ai.messages import ToolReturn

from core.logger import UnifiedLogger
from core.tools.failures import classify_exception, tool_failure_return
from core.web.security import sanitize_url_for_log


logger = UnifiedLogger(tag="web-capabilities")
validation_logger = UnifiedLogger(
    tag="web-capabilities-validation",
    default_sinks=["validation"],
)


def web_tool_failure(
    *,
    tool_name: str,
    strategy: str,
    exc: Exception,
    phase: str,
    urls: list[str] | None = None,
    redactions: list[str] | None = None,
) -> ToolReturn:
    """Log and return one structured web capability failure."""
    classification = classify_exception(exc, phase=phase)
    error_text = str(exc)
    for value in redactions or []:
        if value:
            error_text = error_text.replace(value, "[redacted]")
    for url in urls or []:
        error_text = error_text.replace(url, sanitize_url_for_log(url))
    classification = replace(classification, message=error_text)
    data: dict[str, Any] = {
        "event": "web_capability_failed",
        "status": "failed",
        "capability": tool_name,
        "strategy": strategy,
        "error_type": classification.error_type,
        "failure_kind": classification.failure_kind,
        "retryable": classification.retryable,
        "error": error_text[:500],
    }
    if classification.http_status is not None:
        data["http_status"] = classification.http_status
    if urls:
        data["url_count"] = len(urls)
        data["urls"] = [sanitize_url_for_log(url) for url in urls[:10]]
    logger.warning("web_capability_failed", data=data)
    return tool_failure_return(
        tool_name=tool_name,
        message=f"{tool_name} strategy '{strategy}' failed: {error_text}",
        classification=classification,
        metadata={
            "capability": tool_name,
            "strategy": strategy,
            "url_count": len(urls or []),
        },
    )


def log_web_capability_completed(
    *,
    tool_name: str,
    strategy: str,
    result_count: int,
    duration_seconds: float,
    failure_count: int = 0,
) -> None:
    """Emit compact validation evidence for explicit strategy routing."""
    validation_logger.info(
        "web_capability_completed",
        data={
            "event": "web_capability_completed",
            "status": "completed",
            "capability": tool_name,
            "strategy": strategy,
            "result_count": result_count,
            "failure_count": failure_count,
            "duration_seconds": round(duration_seconds, 3),
        },
    )
