"""Tool-call history integrity helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse

_MODEL_MESSAGE_ADAPTER = TypeAdapter(ModelMessage)


@dataclass(frozen=True)
class ToolHistoryIssue:
    """One tool-call history integrity issue."""

    code: str
    severity: str
    tool_call_id: str
    message_index: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""
        return asdict(self)


@dataclass(frozen=True)
class ToolHistoryIntegrity:
    """Summary of tool-call history integrity."""

    status: str
    tool_call_count: int
    tool_return_count: int
    multi_call_batch_count: int
    multi_return_batch_count: int
    issues: tuple[ToolHistoryIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Return whether no integrity problems were found."""
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""
        return {
            "status": self.status,
            "tool_call_count": self.tool_call_count,
            "tool_return_count": self.tool_return_count,
            "multi_call_batch_count": self.multi_call_batch_count,
            "multi_return_batch_count": self.multi_return_batch_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def analyze_tool_history(messages: Sequence[ModelMessage]) -> ToolHistoryIntegrity:
    """Analyze provider-native messages for tool-call/return integrity."""
    pending: dict[str, int] = {}
    issues: list[ToolHistoryIssue] = []
    call_ids: list[str] = []
    return_ids: list[str] = []
    multi_call_batch_count = 0
    multi_return_batch_count = 0

    for index, message in enumerate(messages):
        tool_calls = _tool_call_ids(message)
        tool_returns = _tool_return_ids(message)
        if len(tool_calls) > 1:
            multi_call_batch_count += 1
        if len(tool_returns) > 1:
            multi_return_batch_count += 1

        for duplicate_id in _duplicates(tool_calls):
            issues.append(
                ToolHistoryIssue(
                    code="duplicate_tool_call_in_message",
                    severity="error",
                    tool_call_id=duplicate_id,
                    message_index=index,
                    detail="A single message contains duplicate tool-call ids.",
                )
            )

        for duplicate_id in _duplicates(tool_returns):
            issues.append(
                ToolHistoryIssue(
                    code="duplicate_tool_return_in_message",
                    severity="error",
                    tool_call_id=duplicate_id,
                    message_index=index,
                    detail="A single message contains duplicate tool-return ids.",
                )
            )

        for tool_call_id in tool_calls:
            call_ids.append(tool_call_id)
            if tool_call_id in pending:
                issues.append(
                    ToolHistoryIssue(
                        code="duplicate_unreturned_tool_call",
                        severity="error",
                        tool_call_id=tool_call_id,
                        message_index=index,
                        detail="A tool-call id was reused before its prior call returned.",
                    )
                )
            pending[tool_call_id] = index

        for tool_call_id in tool_returns:
            return_ids.append(tool_call_id)
            call_index = pending.pop(tool_call_id, None)
            if call_index is None:
                issues.append(
                    ToolHistoryIssue(
                        code="orphan_tool_return",
                        severity="error",
                        tool_call_id=tool_call_id,
                        message_index=index,
                        detail="A tool return has no preceding unmatched tool call.",
                    )
                )
                continue
            if index != call_index + 1:
                issues.append(
                    ToolHistoryIssue(
                        code="non_adjacent_tool_return",
                        severity="warning",
                        tool_call_id=tool_call_id,
                        message_index=index,
                        detail="A tool return is not in the message immediately after its call.",
                    )
                )

    for tool_call_id, call_index in pending.items():
        issues.append(
            ToolHistoryIssue(
                code="orphan_tool_call",
                severity="error",
                tool_call_id=tool_call_id,
                message_index=call_index,
                detail="A tool call has no matching tool return.",
            )
        )

    return ToolHistoryIntegrity(
        status="ok" if not issues else "issues",
        tool_call_count=len(call_ids),
        tool_return_count=len(return_ids),
        multi_call_batch_count=multi_call_batch_count,
        multi_return_batch_count=multi_return_batch_count,
        issues=tuple(issues),
    )


def analyze_tool_history_payloads(payloads: Sequence[dict[str, Any]]) -> ToolHistoryIntegrity:
    """Analyze JSON/dict message payloads for tool-call/return integrity."""
    messages: list[ModelMessage] = []
    issues: list[ToolHistoryIssue] = []
    for index, payload in enumerate(payloads):
        try:
            messages.append(_MODEL_MESSAGE_ADAPTER.validate_python(payload))
        except Exception as exc:  # noqa: BLE001
            issues.append(
                ToolHistoryIssue(
                    code="invalid_message_payload",
                    severity="error",
                    tool_call_id="",
                    message_index=index,
                    detail=f"Message payload could not be decoded: {type(exc).__name__}: {exc}",
                )
            )
    integrity = analyze_tool_history(messages)
    if not issues:
        return integrity
    return ToolHistoryIntegrity(
        status="issues",
        tool_call_count=integrity.tool_call_count,
        tool_return_count=integrity.tool_return_count,
        multi_call_batch_count=integrity.multi_call_batch_count,
        multi_return_batch_count=integrity.multi_return_batch_count,
        issues=(*issues, *integrity.issues),
    )


def _tool_call_ids(message: ModelMessage) -> list[str]:
    if not isinstance(message, ModelResponse):
        return []
    ids: list[str] = []
    for part in getattr(message, "parts", ()) or ():
        if getattr(part, "part_kind", None) != "tool-call":
            continue
        tool_call_id = str(getattr(part, "tool_call_id", "") or "").strip()
        if tool_call_id:
            ids.append(tool_call_id)
    return ids


def _tool_return_ids(message: ModelMessage) -> list[str]:
    if not isinstance(message, ModelRequest):
        return []
    ids: list[str] = []
    for part in getattr(message, "parts", ()) or ():
        if getattr(part, "part_kind", None) != "tool-return":
            continue
        tool_call_id = str(getattr(part, "tool_call_id", "") or "").strip()
        if tool_call_id:
            ids.append(tool_call_id)
    return ids


def _duplicates(values: Sequence[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)
