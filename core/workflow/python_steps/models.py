"""Typed internal models for compiled python_steps workflows."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FileInput:
    """File-based step input source."""

    path: str
    options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VarInput:
    """Variable-based step input source."""

    name: str
    options: dict[str, object] = field(default_factory=dict)


InputSource = FileInput | VarInput


@dataclass(frozen=True)
class FileTarget:
    """File output target."""

    path: str
    options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VarTarget:
    """Variable output target."""

    name: str
    options: dict[str, object] = field(default_factory=dict)


OutputTarget = FileTarget | VarTarget


@dataclass(frozen=True)
class RunStepOp:
    """Operation that references another step by name."""

    step_name: str


@dataclass(frozen=True)
class WriteOp:
    """Operation that writes literal content to an output target."""

    target: OutputTarget
    content: str


@dataclass(frozen=True)
class BranchOp:
    """Operation that chooses one of two actions based on an input target."""

    on: InputSource
    if_empty: "Operation"
    otherwise: "Operation"


Operation = RunStepOp | WriteOp | BranchOp


@dataclass(frozen=True)
class StepDefinition:
    """Compiled python-authored workflow step."""

    name: str
    section_name: str
    model: str | None = None
    prompt: str | None = None
    inputs: list[InputSource] = field(default_factory=list)
    output: OutputTarget | None = None
    run: list[Operation] = field(default_factory=list)
    extras: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CompiledPythonStepsWorkflow:
    """Compiled registry of workflow steps."""

    workflow_id: str
    steps: dict[str, StepDefinition]

