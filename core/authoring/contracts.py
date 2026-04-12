"""Contracts for the experimental Monty-backed authoring runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


BUILTIN_CAPABILITY_NAMES: frozenset[str] = frozenset(
    {
        "retrieve",
        "output",
        "generate",
        "call_tool",
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


class CapabilityHandlerMissingError(AuthoringCapabilityError):
    """Raised when a capability is registered but the host adapter is missing."""


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
class OutputItem:
    """One resolved output target written by output(...)."""

    ref: str
    resolved_ref: str
    mode: str


@dataclass(frozen=True)
class OutputResult:
    """Envelope for output(...) results."""

    type: str
    ref: str
    status: str
    item: OutputItem


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

    messages: tuple[ContextMessage, ...] = ()
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
    """Host-side adapter implemented by the caller of the Monty runtime."""

    def get_monty_inputs(self) -> dict[str, Any]: ...

    def get_monty_dataclasses(self) -> tuple[type, ...]: ...

    async def handle_retrieve(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...

    async def handle_output(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...

    async def handle_generate(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...

    async def handle_call_tool(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...

    async def handle_assemble_context(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...

    async def handle_parse_markdown(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...

    async def handle_import_content(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...

    async def handle_finish(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any: ...


CapabilityHandler = Any


@dataclass(frozen=True)
class AuthoringCapabilityDefinition:
    """Registered capability metadata and runtime adapter."""

    name: str
    doc: str
    handler: CapabilityHandler
    contract: dict[str, Any] = field(default_factory=dict)


def _normalize_string_set(value: Any) -> frozenset[str]:
    """Normalize a sequence of strings into a deduplicated frozenset."""
    return frozenset(_normalize_string_tuple(value))


def _extract_authoring_mapping(frontmatter: Mapping[str, Any]) -> Mapping[str, Any]:
    extracted: dict[str, Any] = {}
    for raw_key, value in frontmatter.items():
        if not isinstance(raw_key, str):
            continue
        if not raw_key.startswith("authoring."):
            continue
        nested_key = raw_key[len("authoring.") :].strip()
        if nested_key:
            extracted[nested_key] = value

    if extracted:
        return extracted
    return {}


def _normalize_string_tuple(value: Any) -> tuple[str, ...]:
    """Normalize frontmatter string lists while rejecting invalid shapes."""
    if value is None:
        return ()
    if isinstance(value, str):
        values = _expand_string_list_literal(value)
    elif isinstance(value, Sequence):
        values = tuple(value)
    else:
        raise AuthoringCapabilityError("frontmatter capability fields must be strings or lists")

    normalized: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise AuthoringCapabilityError("frontmatter capability fields must only contain strings")
        stripped = item.strip()
        if stripped:
            normalized.append(stripped)
    return tuple(normalized)


def _expand_string_list_literal(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return ()
        return tuple(part.strip() for part in inner.split(","))
    return (value,)
