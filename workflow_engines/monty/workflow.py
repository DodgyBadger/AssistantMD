"""Workflow engine shim for the experimental Monty-backed authoring surface."""

from __future__ import annotations

import os

from core.authoring.loader import parse_authoring_template_text
from core.authoring.service import run_authoring_template
from core.constants import ASSISTANTMD_ROOT_DIR, WORKFLOW_DEFINITIONS_DIR


def validate_workflow_definition(
    *,
    workflow_id: str,
    file_path: str,
    sections: dict,
    validated_config: dict,
):
    """Validate Monty workflow structure during load."""
    del sections, validated_config
    with open(file_path, "r", encoding="utf-8") as handle:
        content = handle.read()
    return parse_authoring_template_text(content)


async def run_workflow(job_args: dict, **kwargs):
    """Execute a Monty-authored markdown workflow template."""
    del kwargs
    global_id = job_args["global_id"]
    data_root = job_args["config"]["data_root"]

    if "/" not in global_id:
        raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")

    vault_name, workflow_name = global_id.split("/", 1)
    file_path = os.path.join(
        data_root,
        vault_name,
        ASSISTANTMD_ROOT_DIR,
        WORKFLOW_DEFINITIONS_DIR,
        f"{workflow_name}.md",
    )
    return await run_authoring_template(workflow_id=global_id, file_path=file_path)
