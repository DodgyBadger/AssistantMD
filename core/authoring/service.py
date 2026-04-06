"""Compile-only authoring helpers for candidate workflow text."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.authoring.loader import (
    AuthoringTemplateSource,
    load_authoring_template_file,
    parse_authoring_template_text,
)
from core.authoring.runtime import (
    AuthoringMontyExecutionResult,
    WorkflowAuthoringHost,
    run_authoring_monty,
)
from core.workflow.python_steps.compiler import compile_python_steps_workflow
from core.workflow.python_steps.models import CompiledPythonStepsWorkflow
from core.workflow.python_steps.parser import (
    PythonStepsValidationError,
    parse_python_steps_workflow_text,
)
from core.workflow.parser import validate_config
from core.utils.frontmatter import parse_simple_frontmatter


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


async def run_authoring_template(
    *,
    workflow_id: str,
    file_path: str,
) -> AuthoringMontyExecutionResult:
    """Load one markdown authoring template file and execute its python block."""
    source = load_authoring_template_file(file_path)
    return await _run_loaded_template(workflow_id=workflow_id, source=source)


async def run_authoring_template_text(
    *,
    workflow_id: str,
    content: str,
) -> AuthoringMontyExecutionResult:
    """Parse markdown authoring template text and execute its python block."""
    source = parse_authoring_template_text(content)
    return await _run_loaded_template(workflow_id=workflow_id, source=source)


def compile_candidate_workflow(
    *,
    workflow_id: str,
    content: str,
) -> AuthoringCompileResult:
    """Compile candidate workflow markdown and return structured diagnostics."""
    frontmatter, _body = parse_simple_frontmatter(content, require_frontmatter=False)
    engine_name = str(frontmatter.get("workflow_engine") or "").strip().lower()
    if engine_name == "monty":
        return _compile_monty_candidate_workflow(workflow_id=workflow_id, content=content)

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


def _compile_monty_candidate_workflow(
    *,
    workflow_id: str,
    content: str,
) -> AuthoringCompileResult:
    try:
        frontmatter, _body = parse_simple_frontmatter(
            content,
            require_frontmatter=True,
            missing_error="Workflow file must start with YAML frontmatter (---)",
        )
        vault_name, workflow_name = _split_workflow_id(workflow_id)
        validate_config(frontmatter, vault_name, workflow_name)
        parsed = parse_authoring_template_text(content)
    except ValueError as exc:
        return AuthoringCompileResult(
            ok=False,
            diagnostics=[AuthoringDiagnostic(phase="parse", message=str(exc))],
        )

    return AuthoringCompileResult(
        ok=True,
        summary=AuthoringCompileSummary(
            workflow_id=workflow_id,
            block_count=parsed.block_count,
            block_label=parsed.block_label,
            workflow_name="monty_template",
            step_names=[],
            instructions_present=bool(parsed.body.strip()),
            output_targets={},
        ),
    )


async def _run_loaded_template(
    *,
    workflow_id: str,
    source: AuthoringTemplateSource,
) -> AuthoringMontyExecutionResult:
    frontmatter = dict(source.frontmatter)
    authoring = frontmatter.get("authoring")
    if not isinstance(authoring, dict):
        authoring = {}
    if "capabilities" not in authoring:
        authoring = {**authoring, "capabilities": ["retrieve", "output", "generate"]}
    frontmatter["authoring"] = authoring

    return await run_authoring_monty(
        workflow_id=workflow_id,
        code=source.code,
        host=WorkflowAuthoringHost(workflow_id=workflow_id),
        frontmatter=frontmatter,
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


def _split_workflow_id(workflow_id: str) -> tuple[str, str]:
    """Split workflow_id into vault and workflow name for validation context."""
    if "/" not in workflow_id:
        raise ValueError(
            f"Invalid workflow_id format. Expected 'vault/name', got: {workflow_id}"
        )
    return workflow_id.split("/", 1)
