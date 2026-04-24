"""Contracts for the experimental Monty-backed authoring runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


BUILTIN_CAPABILITY_NAMES: frozenset[str] = frozenset(
    {
        "read_cache",
        "pending_files",
        "generate",
        "call_tool",
        "retrieve_history",
        "assemble_context",
        "parse_markdown",
        "import_content",
        "finish",
    }
)


class AuthoringCapabilityError(ValueError):
    """Base error for capability registration failures."""


class UnknownAuthoringCapabilityError(AuthoringCapabilityError):
    """Raised when code or frontmatter references an unknown capability."""


class AuthoringFinishSignal(RuntimeError):
    """Raised internally when authored code ends execution intentionally."""

    PREFIX = "__authoring_finish__:"

    def __init__(self, *, status: str, reason: str = "") -> None:
        payload = {"status": status, "reason": reason}
        super().__init__(f"{self.PREFIX}{json.dumps(payload, sort_keys=True)}")
        self.status = status
        self.reason = reason

    @classmethod
    def try_parse(cls, value: str) -> tuple[str, str] | None:
        if not isinstance(value, str) or not value.startswith(cls.PREFIX):
            return None
        payload = json.loads(value[len(cls.PREFIX) :])
        status = str(payload.get("status") or "").strip().lower()
        reason = str(payload.get("reason") or "")
        if not status:
            return None
        return status, reason


@dataclass(frozen=True)
class AuthoringCapabilityCall:
    """One sandbox-to-host capability invocation."""

    capability_name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthoringExecutionContext:
    """Stable execution context passed to capability handlers."""

    workflow_id: str
    host: "AuthoringHost"


@dataclass(frozen=True)
class RetrievedItem:
    """One retrieved artifact returned to Monty-authored Python."""

    ref: str | None
    content: str
    exists: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrieveResult:
    """Envelope for retrieve(...) results."""

    type: str
    ref: str
    items: tuple[RetrievedItem, ...] = ()


@dataclass(frozen=True)
class ContextMessage:
    """One normalized chat-history message for downstream context assembly."""

    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoryMessage:
    """One preserved conversation message returned by authoring history retrieval."""

    role: str
    content: str
    message: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExchange:
    """One atomic tool call/return exchange returned by authoring history retrieval."""

    tool_call_id: str
    tool_name: str
    request_message: dict[str, Any]
    response_message: dict[str, Any]
    call_arguments: dict[str, Any] | None = None
    result_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedHistoryResult:
    """Envelope for structured history retrieval into authored Python."""

    source: str
    scope: str
    session_id: str | None
    item_count: int
    items: tuple[HistoryMessage | ToolExchange, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingFilesResult:
    """Envelope for pending_files(...) results."""

    operation: str
    status: str
    items: tuple[RetrievedItem, ...] = ()
    completed_count: int = 0


@dataclass(frozen=True)
class GenerationResult:
    """Envelope for generate(...) results."""

    status: str
    model: str
    output: str


@dataclass(frozen=True)
class CallToolResult:
    """Envelope for call_tool(...) results."""

    name: str
    status: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssembleContextResult:
    """Validated structured context ready for a downstream chat call."""

    messages: tuple[ContextMessage | HistoryMessage | ToolExchange, ...] = ()
    instructions: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarkdownHeading:
    """One markdown heading discovered in parsed content."""

    level: int
    text: str
    line_start: int


@dataclass(frozen=True)
class MarkdownSection:
    """One heading-delimited markdown section."""

    heading: str
    level: int
    content: str
    line_start: int


@dataclass(frozen=True)
class MarkdownCodeBlock:
    """One fenced code block discovered in parsed content."""

    language: str | None
    content: str
    line_start: int | None = None


@dataclass(frozen=True)
class MarkdownImage:
    """One markdown image reference discovered in parsed content."""

    src: str
    alt: str
    title: str | None = None
    line_start: int | None = None


@dataclass(frozen=True)
class ParsedMarkdown:
    """Structured markdown decomposition for authored Python exploration."""

    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    headings: tuple[MarkdownHeading, ...] = ()
    sections: tuple[MarkdownSection, ...] = ()
    code_blocks: tuple[MarkdownCodeBlock, ...] = ()
    images: tuple[MarkdownImage, ...] = ()


@dataclass(frozen=True)
class FinishResult:
    """Envelope for an intentional authored termination."""

    status: str
    reason: str = ""


@runtime_checkable
class AuthoringHost(Protocol):
    """Host-side runtime state exposed to helper executors."""

    def get_monty_inputs(self) -> dict[str, Any]: ...

    def get_monty_dataclasses(self) -> tuple[type, ...]: ...


CapabilityHandler = Any


@dataclass(frozen=True)
class AuthoringCapabilityDefinition:
    """Registered capability metadata and runtime adapter."""

    name: str
    doc: str
    handler: CapabilityHandler
    contract: dict[str, Any] = field(default_factory=dict)
