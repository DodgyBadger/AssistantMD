"""Contracts for the experimental Monty-backed authoring runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


BUILTIN_CAPABILITY_NAMES: frozenset[str] = frozenset(
    {"retrieve", "output", "generate", "call_tool", "import_content"}
)


class AuthoringCapabilityError(ValueError):
    """Base error for capability registration and scoping failures."""


class UnknownAuthoringCapabilityError(AuthoringCapabilityError):
    """Raised when code or frontmatter references an unknown capability."""


class CapabilityNotAllowedError(AuthoringCapabilityError):
    """Raised when sandboxed code tries to call a capability outside its scope."""


class CapabilityHandlerMissingError(AuthoringCapabilityError):
    """Raised when a capability is registered but the host adapter is missing."""


@dataclass(frozen=True)
class AuthoringCapabilityCall:
    """One sandbox-to-host capability invocation."""

    capability_name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthoringCapabilityScope:
    """Frontmatter-derived capability and policy scope for one artifact."""

    enabled: frozenset[str]
    readable_paths: tuple[str, ...] = ()
    readable_cache_refs: tuple[str, ...] = ()
    writable_paths: tuple[str, ...] = ()
    writable_cache_refs: tuple[str, ...] = ()
    import_paths: tuple[str, ...] = ()
    allowed_models: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()

    def allows(self, capability_name: str) -> bool:
        """Return True when the capability is enabled for this execution."""
        return capability_name in self.enabled

    @classmethod
    def from_frontmatter(
        cls,
        frontmatter: Mapping[str, Any] | None,
        *,
        default_enabled: Sequence[str] = (),
    ) -> "AuthoringCapabilityScope":
        """Build a scope from experimental authoring frontmatter."""
        if not frontmatter:
            return cls(enabled=frozenset(default_enabled))

        authoring_config = _extract_authoring_mapping(frontmatter)
        if not isinstance(authoring_config, Mapping):
            authoring_config = frontmatter

        raw_capabilities = authoring_config.get("capabilities")
        if raw_capabilities is None:
            enabled = frozenset(default_enabled)
        elif isinstance(raw_capabilities, Mapping):
            enabled = _normalize_string_set(raw_capabilities.get("enabled", ()))
        else:
            enabled = _normalize_string_set(raw_capabilities)

        return cls(
            enabled=enabled,
            readable_paths=_normalize_string_tuple(authoring_config.get("retrieve.file", ())),
            readable_cache_refs=_normalize_string_tuple(authoring_config.get("retrieve.cache", ())),
            writable_paths=_normalize_string_tuple(authoring_config.get("output.file", ())),
            writable_cache_refs=_normalize_string_tuple(authoring_config.get("output.cache", ())),
            import_paths=_normalize_string_tuple(authoring_config.get("import_paths", ())),
            allowed_models=_normalize_string_tuple(authoring_config.get("models", ())),
            allowed_tools=_normalize_string_tuple(authoring_config.get("tools", ())),
        )


@dataclass(frozen=True)
class AuthoringExecutionContext:
    """Stable execution context passed to capability handlers."""

    workflow_id: str
    host: "AuthoringHost"
    scope: AuthoringCapabilityScope


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

    async def handle_import_content(
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
