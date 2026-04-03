"""Canonical declarative authoring primitives shared across authoring systems."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class File:
    """Declarative file input/output target.

    Args:
        path: Relative vault path or glob-like selector.
        **options: Authoring options such as selector and routing metadata.
    """

    path: str
    options: dict[str, object] = field(default_factory=dict)

    def __init__(self, path: str, **options: object) -> None:
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "options", dict(options))

    def append(self) -> "File":
        """Return a copy with append write mode."""
        return replace(self, options={**self.options, "mode": "append"})

    def replace(self) -> "File":
        """Return a copy with replace write mode."""
        return replace(self, options={**self.options, "mode": "replace"})


@dataclass(frozen=True)
class Var:
    """Declarative variable input/output target.

    Args:
        name: Variable name within the workflow or context runtime.
        **options: Authoring options such as scope or routing metadata.
    """

    name: str
    options: dict[str, object] = field(default_factory=dict)

    def __init__(self, name: str, **options: object) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "options", dict(options))

    def append(self) -> "Var":
        """Return a copy with append write mode."""
        return replace(self, options={**self.options, "mode": "append"})

    def replace(self) -> "Var":
        """Return a copy with replace write mode."""
        return replace(self, options={**self.options, "mode": "replace"})


@dataclass(frozen=True)
class Step:
    """Declarative authoring step.

    Args:
        name: Stable runtime-visible step name.
        prompt: Prompt text for the step.
        model: Optional model alias.
        inputs: Optional list of File/Var sources.
        output: Optional File/Var target.
        **extras: Reserved space for future step capabilities.
    """

    name: str
    prompt: str
    model: str | None = None
    inputs: list[File | Var] = field(default_factory=list)
    output: File | Var | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def __init__(
        self,
        *,
        name: str,
        prompt: str,
        model: str | None = None,
        inputs: list[File | Var] | None = None,
        output: File | Var | None = None,
        **extras: object,
    ) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "inputs", list(inputs or []))
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "extras", dict(extras))


@dataclass(frozen=True)
class Workflow:
    """Declarative sequential workflow definition.

    Args:
        steps: Ordered step list.
        instructions: Optional workflow-level system instructions.
    """

    steps: list[Step]
    instructions: str | None = None

    def __init__(self, *, steps: list[Step], instructions: str | None = None) -> None:
        object.__setattr__(self, "steps", list(steps))
        object.__setattr__(self, "instructions", instructions)

    def run(self) -> "_WorkflowRun":
        """Return the canonical sequential workflow-run operation."""
        return _WorkflowRun(mode="run", step_name=None)

    def run_step(self, step_name: str) -> "_WorkflowRun":
        """Return a targeted single-step workflow-run operation."""
        return _WorkflowRun(mode="run_step", step_name=step_name)


@dataclass(frozen=True)
class _WorkflowRun:
    """Internal authoring marker for workflow execution intent."""

    mode: str
    step_name: str | None


AUTHORING_PRIMITIVE_TYPES: tuple[type[Any], ...] = (File, Step, Var, Workflow)
AUTHORING_PRIMITIVE_NAMES: frozenset[str] = frozenset(
    primitive.__name__ for primitive in AUTHORING_PRIMITIVE_TYPES
)
AUTHORING_TARGET_METHODS: frozenset[str] = frozenset({"append", "replace"})
AUTHORING_PRIMITIVE_METADATA: dict[str, dict[str, object]] = {
    "File": {
        "roles": ["input", "output"],
        "constructor": {
            "path": "Relative vault path or selector pattern.",
            "options": {
                "mode": "Write mode for output usage, such as 'append' or 'replace'.",
                "scope": "Reserved for routing scope metadata.",
                "required": "When true, missing input should be treated as required.",
                "refs_only": "When true, pass references rather than file content.",
                "head": "Optional line limit from the start of matched file content.",
                "tail": "Optional line limit from the end of matched file content.",
                "properties": "Optional frontmatter/property selection metadata.",
                "pending": "Optional selector flag for oldest-unprocessed matching files.",
                "latest": "Optional selector flag for newest matching files.",
                "limit": "Maximum number of matched files to include.",
                "order": "Selector ordering hint.",
                "dir": "Optional directory selection hint.",
            },
        },
        "methods": {
            "append": "Return a copy with append write mode.",
            "replace": "Return a copy with replace write mode.",
        },
    },
    "Var": {
        "roles": ["input", "output"],
        "constructor": {
            "name": "Variable name within the runtime.",
            "options": {
                "mode": "Write mode for output usage, such as 'append' or 'replace'.",
                "scope": "Buffer scope such as 'run' or 'session'.",
                "output": "Optional routing hint for future parity work.",
            },
        },
        "methods": {
            "append": "Return a copy with append write mode.",
            "replace": "Return a copy with replace write mode.",
        },
    },
    "Step": {
        "roles": ["step"],
        "constructor": {
            "name": "Stable runtime-visible step name.",
            "prompt": "Prompt text for the step.",
            "model": "Optional model alias.",
            "inputs": "Optional ordered list of File/Var inputs.",
            "output": "Optional File/Var output target.",
            "extras": "Reserved space for future step capabilities.",
        },
        "methods": {},
    },
    "Workflow": {
        "roles": ["workflow"],
        "constructor": {
            "steps": "Ordered list of Step definitions.",
            "instructions": "Optional workflow-level system instructions.",
        },
        "methods": {
            "run": "Return the canonical sequential workflow-run operation.",
            "run_step": "Return a targeted single-step workflow-run operation.",
        },
    },
}
