"""Shared structured failure envelopes for tool results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import ToolReturn


@dataclass(frozen=True)
class FailureClassification:
    """Machine-readable classification for a tool/API failure."""

    error_type: str
    failure_kind: str
    retryable: bool
    suggested_action: str
    phase: str = "tool_execution"
    message: str = ""
    http_status: int | None = None
    retry_after: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Return JSON-safe metadata for a ToolReturn envelope."""
        payload: dict[str, Any] = {
            "status": "failed",
            "error_type": self.error_type,
            "failure_kind": self.failure_kind,
            "retryable": self.retryable,
            "phase": self.phase,
            "suggested_action": self.suggested_action,
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.retry_after:
            payload["retry_after"] = self.retry_after
        if self.metadata:
            payload.update(self.metadata)
        return payload


@dataclass(frozen=True)
class RetryDecision:
    """Decision for whether and when a retry should be attempted."""

    should_retry: bool
    reason: str
    attempt: int
    max_attempts: int
    delay_seconds: float | None = None
    failure_kind: str | None = None
    retry_after: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        """Return JSON-safe retry decision metadata."""
        payload: dict[str, Any] = {
            "should_retry": self.should_retry,
            "reason": self.reason,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
        }
        if self.delay_seconds is not None:
            payload["delay_seconds"] = self.delay_seconds
        if self.failure_kind:
            payload["failure_kind"] = self.failure_kind
        if self.retry_after:
            payload["retry_after"] = self.retry_after
        return payload


def classify_exception(exc: Exception, *, phase: str = "tool_execution") -> FailureClassification:
    """Classify common network/API/tool exceptions into a stable failure envelope."""
    if isinstance(exc, UsageLimitExceeded):
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="execution_limit",
            retryable=False,
            phase=phase,
            message=str(exc),
            suggested_action=(
                "Do not retry the same broad request. Split the work into smaller scoped steps "
                "or raise the configured execution limit if the scope is intentional."
            ),
        )
    if isinstance(exc, ModelHTTPError):
        status_code = exc.status_code
        body_text = str(exc.body or "")
        lowered = body_text.lower()
        if status_code == 429:
            return FailureClassification(
                error_type=type(exc).__name__,
                failure_kind="rate_limited",
                retryable=True,
                phase=phase,
                message=str(exc),
                http_status=status_code,
                suggested_action="Retry after the provider rate-limit window.",
                metadata={"model_name": exc.model_name},
            )
        if 500 <= status_code <= 599:
            return FailureClassification(
                error_type=type(exc).__name__,
                failure_kind="provider_unavailable",
                retryable=True,
                phase=phase,
                message=str(exc),
                http_status=status_code,
                suggested_action="Retry with backoff; use another model/provider if the outage continues.",
                metadata={"model_name": exc.model_name},
            )
        if status_code in {401, 403} or any(
            token in lowered
            for token in ("api key", "unauthorized", "forbidden", "authentication")
        ):
            return FailureClassification(
                error_type=type(exc).__name__,
                failure_kind="configuration",
                retryable=False,
                phase=phase,
                message=str(exc),
                http_status=status_code,
                suggested_action="Check the model provider secret and account access before retrying.",
                metadata={"model_name": exc.model_name},
            )
        if any(token in lowered for token in ("credit", "billing", "balance", "quota")):
            return FailureClassification(
                error_type=type(exc).__name__,
                failure_kind="billing",
                retryable=False,
                phase=phase,
                message=str(exc),
                http_status=status_code,
                suggested_action=(
                    "Check provider billing, credits, or quota before retrying; "
                    "switch models/providers if another configured option is available."
                ),
                metadata={"model_name": exc.model_name},
            )
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="bad_request",
            retryable=False,
            phase=phase,
            message=str(exc),
            http_status=status_code,
            suggested_action="Change the model request or selected model before retrying.",
            metadata={"model_name": exc.model_name},
        )
    if isinstance(exc, httpx.TimeoutException):
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="transient_network",
            retryable=True,
            phase=phase,
            message=str(exc),
            suggested_action="Retry with backoff, or narrow the request if repeated timeouts occur.",
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        retry_after = exc.response.headers.get("Retry-After")
        if status_code == 429:
            return FailureClassification(
                error_type=type(exc).__name__,
                failure_kind="rate_limited",
                retryable=True,
                phase=phase,
                message=str(exc),
                http_status=status_code,
                retry_after=retry_after,
                suggested_action="Retry after the provider rate-limit window, respecting Retry-After when present.",
            )
        if 500 <= status_code <= 599:
            return FailureClassification(
                error_type=type(exc).__name__,
                failure_kind="provider_unavailable",
                retryable=True,
                phase=phase,
                message=str(exc),
                http_status=status_code,
                retry_after=retry_after,
                suggested_action="Retry with backoff; use another source if the provider remains unavailable.",
            )
        if status_code in {401, 403}:
            return FailureClassification(
                error_type=type(exc).__name__,
                failure_kind="configuration",
                retryable=False,
                phase=phase,
                message=str(exc),
                http_status=status_code,
                suggested_action="Check the provider secret, account access, or tool configuration before retrying.",
            )
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="bad_request",
            retryable=False,
            phase=phase,
            message=str(exc),
            http_status=status_code,
            suggested_action="Change the request parameters before retrying.",
        )
    if isinstance(exc, httpx.RequestError):
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="transient_network",
            retryable=True,
            phase=phase,
            message=str(exc),
            suggested_action="Retry with backoff; check network connectivity if failures continue.",
        )

    lowered = str(exc).lower()
    if any(token in lowered for token in ("timeout", "temporarily", "rate limit", "too many requests")):
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="transient_provider",
            retryable=True,
            phase=phase,
            message=str(exc),
            suggested_action="Retry with backoff; reduce request scope if the failure repeats.",
        )
    if any(token in lowered for token in ("api key", "unauthorized", "forbidden", "authentication")):
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="configuration",
            retryable=False,
            phase=phase,
            message=str(exc),
            suggested_action="Check the provider secret, account access, or tool configuration before retrying.",
        )
    if any(token in lowered for token in ("credit", "billing", "balance", "quota")):
        return FailureClassification(
            error_type=type(exc).__name__,
            failure_kind="billing",
            retryable=False,
            phase=phase,
            message=str(exc),
            suggested_action=(
                "Check provider billing, credits, or quota before retrying; "
                "switch providers if another configured option is available."
            ),
        )
    return FailureClassification(
        error_type=type(exc).__name__,
        failure_kind="unknown",
        retryable=False,
        phase=phase,
        message=str(exc),
        suggested_action="Inspect the error details and adjust the request or configuration before retrying.",
    )


def retry_decision(
    classification: FailureClassification,
    *,
    attempt: int,
    max_attempts: int,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 60.0,
    now: datetime | None = None,
) -> RetryDecision:
    """Return the retry policy decision for a classified failure.

    `attempt` is one-based and represents the failed attempt that just occurred.
    A retry is allowed only when the failure classification is retryable and the
    failed attempt has not already reached `max_attempts`.
    """
    normalized_attempt = max(1, int(attempt))
    normalized_max_attempts = max(1, int(max_attempts))
    if not classification.retryable:
        return RetryDecision(
            should_retry=False,
            reason="not_retryable",
            attempt=normalized_attempt,
            max_attempts=normalized_max_attempts,
            failure_kind=classification.failure_kind,
            retry_after=classification.retry_after,
        )
    if normalized_attempt >= normalized_max_attempts:
        return RetryDecision(
            should_retry=False,
            reason="max_attempts_exhausted",
            attempt=normalized_attempt,
            max_attempts=normalized_max_attempts,
            failure_kind=classification.failure_kind,
            retry_after=classification.retry_after,
        )

    retry_after_delay = _retry_after_delay_seconds(classification.retry_after, now=now)
    if retry_after_delay is not None:
        return RetryDecision(
            should_retry=True,
            reason="retry_after",
            attempt=normalized_attempt,
            max_attempts=normalized_max_attempts,
            delay_seconds=min(retry_after_delay, max_delay_seconds),
            failure_kind=classification.failure_kind,
            retry_after=classification.retry_after,
        )

    delay = min(
        max(0.0, base_delay_seconds) * (2 ** (normalized_attempt - 1)),
        max_delay_seconds,
    )
    return RetryDecision(
        should_retry=True,
        reason="exponential_backoff",
        attempt=normalized_attempt,
        max_attempts=normalized_max_attempts,
        delay_seconds=delay,
        failure_kind=classification.failure_kind,
        retry_after=classification.retry_after,
    )


def _retry_after_delay_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return max(0.0, float(stripped))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return max(0.0, (parsed.astimezone(UTC) - reference.astimezone(UTC)).total_seconds())


def tool_failure_return(
    *,
    tool_name: str,
    message: str,
    classification: FailureClassification,
    metadata: dict[str, Any] | None = None,
) -> ToolReturn:
    """Build a ToolReturn with stable structured failure metadata."""
    payload = classification.to_metadata()
    payload["tool_name"] = tool_name
    if metadata:
        payload.update(metadata)
    detail = classification.message.strip()
    return_value = message if not detail else f"{message}: {detail}"
    return ToolReturn(return_value=return_value, content=None, metadata=payload)
