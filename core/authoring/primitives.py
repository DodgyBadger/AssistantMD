"""Canonical declarative authoring primitives shared across authoring systems."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class DateValue:
    """Typed SDK date token lowered into shared runtime date-pattern semantics."""

    pattern: str
    fmt: str | None = None

    def __str__(self) -> str:
        if self.fmt:
            return f"{{{self.pattern}:{self.fmt}}}"
        return f"{{{self.pattern}}}"


@dataclass(frozen=True)
class PathValue:
    """Typed SDK path expression composed from literal and date-token segments."""

    segments: tuple[str | DateValue, ...]

    def __str__(self) -> str:
        return "/".join(_normalize_path_segment(segment) for segment in self.segments)


class _DateNamespace:
    """SDK-owned date helpers for workflow path composition."""

    def today(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("today", fmt=fmt)

    def yesterday(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("yesterday", fmt=fmt)

    def tomorrow(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("tomorrow", fmt=fmt)

    def this_week(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("this-week", fmt=fmt)

    def last_week(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("last-week", fmt=fmt)

    def next_week(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("next-week", fmt=fmt)

    def this_month(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("this-month", fmt=fmt)

    def last_month(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("last-month", fmt=fmt)

    def day_name(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("day-name", fmt=fmt)

    def month_name(self, *, fmt: str | None = None) -> DateValue:
        return DateValue("month-name", fmt=fmt)


class _PathNamespace:
    """SDK-owned path helpers for workflow-safe path composition."""

    def join(self, *segments: str | DateValue | PathValue) -> PathValue:
        if not segments:
            raise ValueError("path.join() requires at least one segment")
        flattened: list[str | DateValue] = []
        for segment in segments:
            if isinstance(segment, PathValue):
                flattened.extend(segment.segments)
                continue
            if not isinstance(segment, str | DateValue):
                raise TypeError("path.join() segments must be strings or date values")
            flattened.append(segment)
        return PathValue(tuple(flattened))


date = _DateNamespace()
path = _PathNamespace()


@dataclass(frozen=True)
class File:
    """Declarative file input/output target.

    Args:
        path: Relative vault path or glob-like selector.
        **options: Authoring options such as selector and routing metadata.
    """

    path: str
    options: dict[str, object] = field(default_factory=dict)

    def __init__(self, path: str | PathValue, **options: object) -> None:
        object.__setattr__(self, "path", str(path))
        object.__setattr__(self, "options", dict(options))

    def append(self) -> "File":
        """Return a copy with append write mode."""
        return replace(self, options={**self.options, "mode": "append"})

    def replace(self) -> "File":
        """Return a copy with replace write mode."""
        return replace(self, options={**self.options, "mode": "replace"})

    def new(self) -> "File":
        """Return a copy with numbered-new write mode."""
        return replace(self, options={**self.options, "mode": "new"})


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

    def new(self) -> "Var":
        """Return a copy with numbered-new write mode."""
        return replace(self, options={**self.options, "mode": "new"})


@dataclass(frozen=True)
class Step:
    """Declarative authoring step.

    Args:
        name: Stable runtime-visible step name.
        prompt: Prompt text for the step.
        model: Optional model alias.
        inputs: Optional list of File/Var sources.
        output: Optional File/Var target.
        outputs: Optional list of File/Var targets.
        **extras: Reserved space for future step capabilities.
    """

    name: str
    prompt: str
    model: str | None = None
    inputs: list[File | Var] = field(default_factory=list)
    output: File | Var | None = None
    outputs: list[File | Var] = field(default_factory=list)
    extras: dict[str, object] = field(default_factory=dict)

    def __init__(
        self,
        *,
        name: str,
        prompt: str,
        model: str | None = None,
        inputs: list[File | Var] | None = None,
        output: File | Var | None = None,
        outputs: list[File | Var] | None = None,
        **extras: object,
    ) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "inputs", list(inputs or []))
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "outputs", list(outputs or []))
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
AUTHORING_HELPER_NAMES: frozenset[str] = frozenset({"date", "path"})
AUTHORING_TARGET_METHODS: frozenset[str] = frozenset({"append", "replace", "new"})
AUTHORING_HELPER_OBJECTS: dict[str, object] = {
    "date": date,
    "path": path,
}
AUTHORING_PRIMITIVE_METADATA: dict[str, dict[str, object]] = {
    "File": {
        "roles": ["input", "output"],
        "constructor": {
            "path": "Relative vault path or selector pattern.",
            "options": {
                "mode": "Write mode for output usage, such as 'append' or 'replace'.",
                "header": "Optional output header template for file writes.",
                "scope": "Reserved for routing scope metadata.",
                "required": "When true, missing input should be treated as required.",
                "refs_only": "When true, pass references rather than file content.",
                "images": "Image handling policy such as 'auto' or 'ignore'.",
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
            "new": "Return a copy with numbered-new write mode.",
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
            "new": "Return a copy with numbered-new write mode.",
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
            "outputs": "Optional ordered list of File/Var output targets.",
            "extras": (
                "Reserved space for future step capabilities such as "
                "tools=['internal_api'] or run_on='daily'."
            ),
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
AUTHORING_HELPER_METADATA: dict[str, dict[str, object]] = {
    "date": {
        "doc": "SDK-owned workflow date helpers for path composition. These are not stdlib datetime objects.",
        "methods": {
            "today": "Return the workflow 'today' token. Optional fmt= uses workflow format tokens such as 'YYYYMMDD'.",
            "yesterday": "Return the workflow 'yesterday' token.",
            "tomorrow": "Return the workflow 'tomorrow' token.",
            "this_week": "Return the workflow 'this-week' token.",
            "last_week": "Return the workflow 'last-week' token.",
            "next_week": "Return the workflow 'next-week' token.",
            "this_month": "Return the workflow 'this-month' token.",
            "last_month": "Return the workflow 'last-month' token.",
            "day_name": "Return the workflow 'day-name' token.",
            "month_name": "Return the workflow 'month-name' token.",
        },
    },
    "path": {
        "doc": "SDK-owned workflow path helpers for composing relative vault paths from literal and date-token segments.",
        "methods": {
            "join": "Join literal path segments and date tokens into one relative workflow path.",
        },
    },
}


def _normalize_path_segment(value: str | DateValue) -> str:
    if isinstance(value, DateValue):
        return str(value)
    return value.strip("/")
