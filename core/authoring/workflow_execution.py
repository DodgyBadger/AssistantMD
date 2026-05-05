"""Shared execution helpers for loaded authoring workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from core.authoring.service import run_authoring_template
from core.runtime.state import get_runtime_context


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Normalized result for one workflow execution."""

    success: bool
    global_id: str
    status: str
    execution_time_seconds: float
    output_files: list[str] = field(default_factory=list)
    reason: str | None = None
    details: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the stable dictionary contract used by API and tool callers."""
        return {
            "success": self.success,
            "global_id": self.global_id,
            "status": self.status,
            "execution_time_seconds": self.execution_time_seconds,
            "output_files": list(self.output_files),
            "reason": self.reason,
            "details": list(self.details),
            "message": self.message,
        }


def format_workflow_load_errors(loader: Any, global_id: str) -> str:
    """Format loader errors for a workflow id, if any were captured."""
    if "/" not in global_id:
        return ""

    vault, name = global_id.split("/", 1)
    matches = [
        error
        for error in loader.get_configuration_errors()
        if error.vault == vault and (error.workflow_name == name or error.workflow_name is None)
    ]
    if not matches:
        return ""

    deduped = []
    seen = set()
    for error in matches:
        key = (error.error_type, error.error_message, error.file_path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(error)

    lines = ["workflow_configuration_errors:"]
    for error in deduped[:5]:
        lines.append(
            f"- [{error.error_type}] {error.error_message} (file: {error.file_path})"
        )
    if len(deduped) > 5:
        lines.append(f"- ... and {len(deduped) - 5} more")
    return "\n".join(lines)


async def execute_workflow_by_id(
    global_id: str,
    *,
    step_name: str | None = None,
    expect_failure: bool = False,
    include_load_errors: bool = False,
) -> WorkflowExecutionResult:
    """Resolve and execute one workflow by global id."""
    if "/" not in global_id:
        raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")

    runtime = get_runtime_context()
    loader = runtime.workflow_loader
    try:
        loaded = await loader.load_workflows(force_reload=True, target_global_id=global_id)
    except Exception as exc:
        if include_load_errors:
            load_errors = format_workflow_load_errors(loader, global_id)
            if load_errors:
                raise ValueError(
                    f"Workflow load failed for '{global_id}': {exc}\n{load_errors}"
                ) from exc
        raise

    if not loaded:
        raise ValueError(f"Workflow not found: {global_id}")

    target = loaded[0]
    await loader.ensure_workflow_directories(target)

    started = perf_counter()
    execution_result = await run_authoring_template(
        workflow_id=target.global_id,
        file_path=target.file_path,
        step_name=step_name,
        expect_failure=expect_failure,
    )
    elapsed = perf_counter() - started
    terminal_status = str(getattr(execution_result, "status", "completed") or "completed")
    terminal_reason = str(getattr(execution_result, "reason", "") or "")

    return WorkflowExecutionResult(
        success=True,
        global_id=target.global_id,
        status=terminal_status,
        execution_time_seconds=elapsed,
        output_files=[],
        reason=terminal_reason or None,
        details=[],
        message=(
            f"Workflow '{target.global_id}' {terminal_status} in {elapsed:.2f} seconds"
            + (f": {terminal_reason}" if terminal_reason else "")
        ),
    )
