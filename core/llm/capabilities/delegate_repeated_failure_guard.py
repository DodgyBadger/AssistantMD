"""Delegate-local circuit breaker for repeated identical structured failures."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ToolReturn

from core.logger import UnifiedLogger
from core.tools.failures import (
    FailureClassification,
    classify_tool_result_state,
    tool_failure_return,
)

logger = UnifiedLogger(tag="delegate-tool")


class DelegateRepeatedFailureGuard:
    """Track one child run's consecutive identical structured tool failures."""

    def __init__(self, *, limit: int, session_id: str) -> None:
        self.limit = max(limit, 0)
        self.session_id = session_id
        self._last_failed_fingerprint: str | None = None
        self._consecutive_failures = 0
        self._lock = asyncio.Lock()

    async def execute(
        self,
        *,
        tool_name: str,
        args: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Execute or block one child tool call and update the failure streak."""
        if self.limit <= 0:
            return await handler(args)

        fingerprint = _tool_call_fingerprint(tool_name, args)
        async with self._lock:
            should_block = (
                fingerprint == self._last_failed_fingerprint
                and self._consecutive_failures >= self.limit
            )
            failure_count = self._consecutive_failures
        if should_block:
            logger.add_sink("validation").warning(
                "delegate_repeated_tool_failure_blocked",
                data={
                    "event": "delegate_repeated_tool_failure_blocked",
                    "workflow_id": self.session_id,
                    "tool_name": tool_name,
                    "failure_count": failure_count,
                    "limit": self.limit,
                },
            )
            return tool_failure_return(
                tool_name=tool_name,
                message="Delegate blocked an unchanged tool call after repeated failures",
                classification=FailureClassification(
                    error_type="RepeatedToolFailure",
                    failure_kind="repeated_tool_failure",
                    retryable=False,
                    phase="delegate_child_tool_execution",
                    message=(
                        f"The same tool and arguments already failed {failure_count} times."
                    ),
                    suggested_action=(
                        "Do not retry this call unchanged. Correct the arguments, use a different "
                        "approach, or return the blocker to the parent."
                    ),
                ),
                metadata={
                    "repeated_failure_limit": self.limit,
                    "blocked_failure_count": failure_count,
                },
            )

        try:
            result = await handler(args)
        except Exception:
            # Only consecutive structured returns participate in this guard. An
            # exception follows a separate failure contract and breaks the streak.
            async with self._lock:
                self._last_failed_fingerprint = None
                self._consecutive_failures = 0
            raise
        async with self._lock:
            if _is_structured_failure(result):
                if fingerprint == self._last_failed_fingerprint:
                    self._consecutive_failures += 1
                else:
                    self._last_failed_fingerprint = fingerprint
                    self._consecutive_failures = 1
            else:
                self._last_failed_fingerprint = None
                self._consecutive_failures = 0
        return result


def build_delegate_repeated_failure_capability(
    *,
    limit: int,
    session_id: str,
) -> Hooks | None:
    """Build the child-run hook, or no capability when the guard is disabled."""
    if limit <= 0:
        return None
    guard = DelegateRepeatedFailureGuard(limit=limit, session_id=session_id)
    hooks = Hooks(id="delegate-repeated-failure-guard")

    @hooks.on.tool_execute
    async def guard_tool_execution(
        ctx: Any,
        *,
        call: Any,
        tool_def: Any,
        args: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        del ctx, tool_def
        return await guard.execute(
            tool_name=str(call.tool_name),
            args=args,
            handler=handler,
        )

    return hooks


def _tool_call_fingerprint(tool_name: str, args: Any) -> str:
    try:
        normalized_args = json.dumps(
            args,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        normalized_args = str(args)
    return f"{tool_name}\n{normalized_args}"


def _is_structured_failure(result: Any) -> bool:
    if not isinstance(result, ToolReturn) or not isinstance(result.metadata, dict):
        return False
    return classify_tool_result_state(metadata=result.metadata) == "failed"
