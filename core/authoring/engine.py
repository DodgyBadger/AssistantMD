"""Monty authoring engine — validates and executes Python-block workflow templates."""

from __future__ import annotations

from core.authoring.template_loader import parse_authoring_template_text
from core.runtime.state import get_runtime_context


def validate_workflow_definition(
    *,
    workflow_id: str,
    file_path: str,
    sections: dict,
    validated_config: dict,
) -> None:
    """Validate workflow structure by parsing the Python block at load time."""
    del sections, validated_config, workflow_id
    with open(file_path, "r", encoding="utf-8") as handle:
        content = handle.read()
    parse_authoring_template_text(content)


async def run_workflow(job_args: dict, **kwargs) -> object:
    """Execute a Monty-authored markdown workflow template."""
    global_id = job_args["global_id"]
    step_name = kwargs.get("step_name")
    expect_failure = bool(kwargs.get("expected_failure", False))

    if "/" not in global_id:
        raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")

    runtime = get_runtime_context()
    return await runtime.workflow_governor.execute_workflow(
        global_id=global_id,
        source="scheduler",
        step_name=step_name,
        expect_failure=expect_failure,
    )
