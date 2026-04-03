"""Compile-only authoring helpers for candidate workflow text."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.workflow.python_steps.compiler import compile_python_steps_workflow
from core.workflow.python_steps.models import CompiledPythonStepsWorkflow
from core.workflow.python_steps.parser import (
    PythonStepsValidationError,
    parse_python_steps_workflow_text,
)


@dataclass(frozen=True)
class AuthoringDiagnostic:
    """Structured diagnostic returned from compile-only authoring checks."""

    phase: str
    message: str
    section_name: str | None = None


@dataclass(frozen=True)
class AuthoringCompileSummary:
    """Compact summary of a successfully compiled candidate workflow."""

    workflow_id: str
    block_count: int
    block_label: str | None
    workflow_name: str
    step_names: list[str]
    instructions_present: bool
    output_targets: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthoringCompileResult:
    """Result of compile-only candidate workflow validation."""

    ok: bool
    diagnostics: list[AuthoringDiagnostic] = field(default_factory=list)
    summary: AuthoringCompileSummary | None = None


def compile_candidate_workflow(
    *,
    workflow_id: str,
    content: str,
) -> AuthoringCompileResult:
    """Compile candidate workflow markdown and return structured diagnostics."""
    try:
        parsed = parse_python_steps_workflow_text(workflow_id=workflow_id, content=content)
        compiled = compile_python_steps_workflow(parsed)
    except PythonStepsValidationError as exc:
        return AuthoringCompileResult(
            ok=False,
            diagnostics=[
                AuthoringDiagnostic(
                    phase=exc.phase,
                    message=str(exc),
                    section_name=exc.section_name,
                )
            ],
        )
    except ValueError as exc:
        return AuthoringCompileResult(
            ok=False,
            diagnostics=[AuthoringDiagnostic(phase="parse", message=str(exc))],
        )

    return AuthoringCompileResult(
        ok=True,
        summary=_build_summary(parsed_workflow=parsed, compiled=compiled),
    )


def _build_summary(
    *,
    parsed_workflow,
    compiled: CompiledPythonStepsWorkflow,
) -> AuthoringCompileSummary:
    output_targets = {
        step_name: _output_label(step.output)
        for step_name, step in compiled.steps.items()
    }
    return AuthoringCompileSummary(
        workflow_id=compiled.workflow_id,
        block_count=parsed_workflow.block_count,
        block_label=parsed_workflow.block_label,
        workflow_name=compiled.workflow.declaration_name,
        step_names=compiled.workflow.step_names,
        instructions_present=compiled.workflow.instructions is not None,
        output_targets=output_targets,
    )


def _output_label(output_target) -> str | None:
    if output_target is None:
        return None
    target_type = type(output_target).__name__.replace("Target", "").lower()
    target_value = getattr(output_target, "path", None) or getattr(output_target, "name", None)
    return f"{target_type}:{target_value}"
