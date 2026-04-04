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
OutputTargets = list[OutputTarget]


@dataclass(frozen=True)
class StepDefinition:
    """Compiled python-authored workflow step."""

    declaration_name: str
    name: str
    model: str | None = None
    prompt: str | None = None
    inputs: list[InputSource] = field(default_factory=list)
    output: OutputTarget | None = None
    outputs: list[OutputTarget] = field(default_factory=list)
    extras: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowDefinition:
    """Compiled sequential workflow definition."""

    declaration_name: str
    instructions: str | None = None
    step_names: list[str] = field(default_factory=list)
    step_declarations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CompiledPythonStepsWorkflow:
    """Compiled registry of workflow steps and workflow execution order."""

    workflow_id: str
    workflow: WorkflowDefinition
    steps: dict[str, StepDefinition]
