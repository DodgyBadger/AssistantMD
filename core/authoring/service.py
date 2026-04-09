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
from core.constants import VALID_WEEK_DAYS
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
    docstring_summary: str | None
    workflow_name: str
    instructions_present: bool


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
    if engine_name != "monty":
        return AuthoringCompileResult(
            ok=False,
            diagnostics=[
                AuthoringDiagnostic(
                    phase="parse",
                    message=(
                        "Compile-only authoring currently supports workflow_engine: monty. "
                        f"Got workflow_engine: {engine_name or '(missing)'}"
                    ),
                )
            ],
        )
    return _compile_monty_candidate_workflow(workflow_id=workflow_id, content=content)


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
            docstring_summary=parsed.docstring_summary,
            workflow_name="monty_template",
            instructions_present=bool(parsed.body.strip()),
        ),
    )


async def _run_loaded_template(
    *,
    workflow_id: str,
    source: AuthoringTemplateSource,
) -> AuthoringMontyExecutionResult:
    frontmatter = dict(source.frontmatter)
    authoring = _extract_authoring_frontmatter(frontmatter)
    frontmatter["authoring"] = authoring
    week_start_day = _resolve_week_start_day(frontmatter)

    return await run_authoring_monty(
        workflow_id=workflow_id,
        code=source.code,
        host=WorkflowAuthoringHost(workflow_id=workflow_id, week_start_day=week_start_day),
        frontmatter=frontmatter,
    )


def _extract_authoring_frontmatter(frontmatter: dict[str, object]) -> dict[str, object]:
    extracted: dict[str, object] = {}
    for raw_key, value in frontmatter.items():
        if isinstance(raw_key, str) and raw_key.startswith("authoring."):
            nested_key = raw_key[len("authoring.") :].strip()
            if nested_key:
                extracted[nested_key] = value
    return extracted

def _split_workflow_id(workflow_id: str) -> tuple[str, str]:
    """Split workflow_id into vault and workflow name for validation context."""
    if "/" not in workflow_id:
        raise ValueError(
            f"Invalid workflow_id format. Expected 'vault/name', got: {workflow_id}"
        )
    return workflow_id.split("/", 1)


def _resolve_week_start_day(frontmatter: dict[str, object]) -> int:
    """Resolve workflow week_start_day frontmatter to 0=Monday .. 6=Sunday."""
    raw_value = frontmatter.get("week_start_day", frontmatter.get("week-start-day", "monday"))
    if isinstance(raw_value, int) and 0 <= raw_value <= 6:
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in VALID_WEEK_DAYS:
            return VALID_WEEK_DAYS.index(normalized)
    return 0
