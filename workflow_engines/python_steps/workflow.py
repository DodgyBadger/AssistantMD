"""Thin compatibility shim for the experimental python_steps engine."""

from __future__ import annotations

from core.workflow.python_steps.executor import run_python_steps_workflow
from core.workflow.python_steps.parser import validate_python_steps_workflow_definition


def validate_workflow_definition(
    *,
    workflow_id: str,
    file_path: str,
    sections: dict,
    validated_config: dict,
):
    """Validate python_steps workflow structure during load."""
    return validate_python_steps_workflow_definition(
        workflow_id=workflow_id,
        file_path=file_path,
        sections=sections,
        validated_config=validated_config,
    )


async def run_workflow(job_args: dict, **kwargs):
    """Compatibility entrypoint that delegates to the core python_steps runtime."""
    await run_python_steps_workflow(job_args, **kwargs)
