"""
Workflow run tool for vault-scoped workflow discovery and execution.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.runtime.state import RuntimeStateError, get_runtime_context
from core.scheduling.jobs import create_job_args
from .base import BaseTool


logger = UnifiedLogger(tag="workflow-run-tool")


class WorkflowRun(BaseTool):
    """Run workflows in the current vault and list available workflow names."""

    allow_routing = True

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the workflow run tool bound to the current vault path."""

        async def workflow_run(
            *,
            operation: str,
            workflow_name: str = "",
            step_name: str = "",
        ) -> str:
            """Run or list workflows in the current vault.

            :param operation: Operation name (list, run)
            :param workflow_name: Workflow name relative to vault (required for run)
            :param step_name: Optional step name to execute (run only)
            """
            try:
                op = (operation or "").strip().lower()
                runtime = get_runtime_context()
                vault_name = cls._resolve_vault_name(vault_path, runtime.config.data_root)

                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "workflow_run",
                        "operation": op,
                        "vault": vault_name,
                    },
                )

                if op == "list":
                    return await cls._list_workflows(vault_name)

                if op == "run":
                    name = (workflow_name or "").strip()
                    if not name:
                        return "workflow_name is required for operation='run'."
                    if cls._is_invalid_workflow_name(name):
                        return "Invalid workflow_name. Use a vault-relative name (e.g. 'daily' or 'folder/daily') without '..'."

                    global_id = f"{vault_name}/{name}"
                    single_step = (step_name or "").strip() or None
                    try:
                        result = await cls._execute_workflow(global_id, single_step)
                        return cls._format_run_result(result)
                    except Exception as exc:  # pylint: disable=broad-except
                        return cls._format_run_error(global_id, single_step, exc)

                return "Unknown operation. Available: list, run"
            except RuntimeStateError as exc:
                return f"Runtime unavailable: {exc}"
            except Exception as exc:  # pylint: disable=broad-except
                return f"Error performing '{operation}' operation: {exc}"

        return Tool(workflow_run, name="workflow_run")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for workflow execution."""
        return """
## workflow_run usage instructions

Discovery:
- workflow_run(operation="list")

Execution:
- workflow_run(operation="run", workflow_name="weekly-planner")
- workflow_run(operation="run", workflow_name="weekly-planner", step_name="Monday - due")

Notes:
- Vault is inferred from current chat/workflow context.
- Use workflow names relative to the current vault.
"""

    @staticmethod
    def _resolve_vault_name(vault_path: str | None, data_root: Path) -> str:
        if not vault_path:
            raise ValueError("vault_path is required for workflow_run")

        vault = Path(vault_path).resolve()
        root = Path(data_root).resolve()

        try:
            relative = vault.relative_to(root)
        except ValueError as exc:
            raise ValueError("vault_path must be inside configured data_root") from exc

        if not relative.parts:
            raise ValueError("vault_path must point to a vault directory under data_root")

        return relative.parts[0]

    @staticmethod
    def _is_invalid_workflow_name(name: str) -> bool:
        normalized = name.replace("\\", "/")
        return (
            normalized.startswith("/")
            or ".." in normalized
            or normalized.endswith("/")
            or normalized == "."
        )

    @staticmethod
    async def _list_workflows(vault_name: str) -> str:
        runtime = get_runtime_context()
        workflows = await runtime.workflow_loader.load_workflows(force_reload=True)
        current_vault = [wf for wf in workflows if wf.vault == vault_name]

        if not current_vault:
            return f"No workflows found for vault '{vault_name}'."

        lines = [f"Workflows in vault '{vault_name}':"]
        for workflow in sorted(current_vault, key=lambda item: item.name.lower()):
            description = (workflow.description or "").strip() or "(no description)"
            lines.append(f"- {workflow.name}: {description}")
        return "\n".join(lines)

    @staticmethod
    def _format_run_result(result: dict) -> str:
        return "\n".join(
            [
                f"success: {result.get('success', False)}",
                f"global_id: {result.get('global_id', '')}",
                f"execution_time_seconds: {result.get('execution_time_seconds', 0)}",
                f"message: {result.get('message', '')}",
            ]
        )

    @staticmethod
    def _format_run_error(global_id: str, step_name: str | None, exc: Exception) -> str:
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tail = "".join(tb_lines).strip().splitlines()[-12:]
        failed_step = getattr(exc, "step_name", None) or step_name or ""
        template_pointer = getattr(exc, "template_pointer", "")
        phase = getattr(exc, "phase", "")
        lines = [
            "success: False",
            f"global_id: {global_id}",
            f"step_name: {failed_step}",
            f"error_type: {type(exc).__name__}",
            f"phase: {phase}",
            f"template_pointer: {template_pointer}",
            f"message: {exc}",
        ]
        if tail:
            lines.append("traceback_tail:")
            lines.extend([f"  {line}" for line in tail])
        return "\n".join(lines)

    @staticmethod
    def _format_load_errors(loader, global_id: str) -> str:
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

    @staticmethod
    async def _execute_workflow(global_id: str, step_name: str | None) -> dict:
        if "/" not in global_id:
            raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")

        runtime = get_runtime_context()
        loader = runtime.workflow_loader
        try:
            loaded = await loader.load_workflows(force_reload=True, target_global_id=global_id)
        except Exception as exc:
            load_errors = WorkflowRun._format_load_errors(loader, global_id)
            if load_errors:
                raise ValueError(
                    f"Workflow load failed for '{global_id}': {exc}\n{load_errors}"
                ) from exc
            raise
        if not loaded:
            raise ValueError(f"Workflow not found: {global_id}")

        target = loaded[0]
        await loader.ensure_workflow_directories(target)

        kwargs = {}
        if step_name is not None:
            kwargs["step_name"] = step_name

        started = datetime.now()
        job_args = create_job_args(target.global_id)
        await target.workflow_function(job_args, **kwargs)
        elapsed = (datetime.now() - started).total_seconds()

        return {
            "success": True,
            "global_id": target.global_id,
            "execution_time_seconds": elapsed,
            "output_files": [],
            "message": f"Workflow '{target.global_id}' executed successfully in {elapsed:.2f} seconds",
        }
