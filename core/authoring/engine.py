"""Monty authoring engine — validates and executes Python-block workflow templates."""

from __future__ import annotations

from core.authoring.template_loader import parse_authoring_template_text
from core.authoring.service import run_authoring_template


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
    del kwargs
    global_id = job_args["global_id"]
    file_path = job_args["file_path"]

    if "/" not in global_id:
        raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")

    return await run_authoring_template(workflow_id=global_id, file_path=file_path)
