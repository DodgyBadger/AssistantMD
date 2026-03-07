"""
Workflow run tool for vault-scoped workflow discovery and execution.
"""

from __future__ import annotations

import traceback
import os
import re
from datetime import datetime
from pathlib import Path

from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.runtime.state import RuntimeStateError, get_runtime_context
from core.scheduling.jobs import create_job_args
from core.constants import ASSISTANTMD_ROOT_DIR, WORKFLOW_DEFINITIONS_DIR
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

            :param operation: Operation name (list, run, enable_workflow, disable_workflow)
            :param workflow_name: Workflow name relative to AssistantMD/Workflows (required for run/enable/disable)
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
                    name = cls._normalize_workflow_name_input(workflow_name)
                    if not name:
                        return "workflow_name is required for operation='run'."
                    if "/app/data/" in name:
                        return "Invalid workflow_name. Runtime filesystem roots are not allowed; pass vault-internal workflow names from workflow_run(operation=\"list\")."
                    if cls._is_invalid_workflow_name(name):
                        return "Invalid workflow_name. Use a vault-relative name (e.g. 'daily' or 'folder/daily') without '..'."

                    global_id = f"{vault_name}/{name}"
                    single_step = (step_name or "").strip() or None
                    try:
                        result = await cls._execute_workflow(global_id, single_step)
                        return cls._format_run_result(result)
                    except Exception as exc:  # pylint: disable=broad-except
                        return cls._format_run_error(global_id, single_step, exc)

                if op in {"enable_workflow", "disable_workflow"}:
                    name = cls._normalize_workflow_name_input(workflow_name)
                    if not name:
                        return f"workflow_name is required for operation='{op}'."
                    if "/app/data/" in name:
                        return "Invalid workflow_name. Runtime filesystem roots are not allowed; pass vault-internal workflow names from workflow_run(operation=\"list\")."
                    if cls._is_invalid_workflow_name(name):
                        return "Invalid workflow_name. Use a vault-relative name (e.g. 'daily' or 'folder/daily') without '..'."
                    result = await cls._set_workflow_enabled_state(
                        operation=op,
                        vault_name=vault_name,
                        workflow_name=name,
                    )
                    return cls._format_lifecycle_result(result)

                return "Unknown operation. Available: list, run, enable_workflow, disable_workflow"
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

Lifecycle:
- workflow_run(operation="enable_workflow", workflow_name="weekly-planner")
- workflow_run(operation="disable_workflow", workflow_name="weekly-planner")

Notes:
- Vault is inferred from current chat/workflow context.
- Use workflow names relative to AssistantMD/Workflows in the current vault.
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
    def _normalize_workflow_name_input(name: str) -> str:
        """Normalize workflow_name into canonical loader format (e.g. ops/daily)."""
        normalized = (name or "").strip().replace("\\", "/")
        if not normalized:
            return ""

        if normalized.startswith("/app/data/"):
            return normalized

        if normalized.startswith("/"):
            return normalized

        prefixes = (
            f"{ASSISTANTMD_ROOT_DIR}/{WORKFLOW_DEFINITIONS_DIR}/",
            f"{WORKFLOW_DEFINITIONS_DIR}/",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break

        if normalized.endswith(".md"):
            normalized = normalized[:-3]

        return normalized.strip("/")

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
            enabled_display = WorkflowRun._resolve_enabled_state_from_frontmatter(
                file_path=workflow.file_path,
                fallback=bool(workflow.enabled),
            )
            lines.append(
                f"- workflow_name: {workflow.name} | workflow_id: {workflow.global_id} | enabled: {enabled_display} | description: {description}"
            )
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
    def _format_lifecycle_result(result: dict) -> str:
        lines = [
            f"success: {result.get('success', False)}",
            f"operation: {result.get('operation', '')}",
            f"workflow_name: {result.get('workflow_name', '')}",
            f"global_id: {result.get('global_id', '')}",
            f"status: {result.get('status', '')}",
            f"enabled_before: {result.get('enabled_before', '')}",
            f"enabled_after: {result.get('enabled_after', '')}",
            f"message: {result.get('message', '')}",
        ]
        return "\n".join(lines)

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

    @staticmethod
    async def _set_workflow_enabled_state(
        *,
        operation: str,
        vault_name: str,
        workflow_name: str,
    ) -> dict:
        runtime = get_runtime_context()
        desired_enabled = operation == "enable_workflow"

        workflows = await runtime.workflow_loader.load_workflows(force_reload=True)
        current_vault = [wf for wf in workflows if wf.vault == vault_name]
        target = next((wf for wf in current_vault if wf.name == workflow_name), None)

        attempted_global_id = f"{vault_name}/{workflow_name}"
        if not target:
            status = "not_found"
            result = {
                "success": False,
                "operation": operation,
                "workflow_name": workflow_name,
                "global_id": attempted_global_id,
                "status": status,
                "enabled_before": "",
                "enabled_after": "",
                "message": f"Workflow not found: {attempted_global_id}",
            }
            logger.set_sinks(["validation"]).info(
                "workflow_lifecycle_changed",
                data={
                    "operation": operation,
                    "workflow_id": attempted_global_id,
                    "status": status,
                },
            )
            return result

        enabled_before = WorkflowRun._resolve_enabled_state_from_frontmatter(
            file_path=target.file_path,
            fallback=bool(target.enabled),
        )
        if enabled_before == desired_enabled:
            status = "already_enabled" if desired_enabled else "already_disabled"
            result = {
                "success": True,
                "operation": operation,
                "workflow_name": workflow_name,
                "global_id": target.global_id,
                "status": status,
                "enabled_before": enabled_before,
                "enabled_after": enabled_before,
                "message": f"Workflow '{target.global_id}' is already {'enabled' if desired_enabled else 'disabled'}.",
            }
            logger.set_sinks(["validation"]).info(
                "workflow_lifecycle_changed",
                data={
                    "operation": operation,
                    "workflow_id": target.global_id,
                    "status": status,
                    "enabled_before": enabled_before,
                    "enabled_after": enabled_before,
                },
            )
            return result

        WorkflowRun._write_enabled_frontmatter(
            file_path=target.file_path,
            enabled=desired_enabled,
            vault_name=vault_name,
            data_root=str(runtime.config.data_root),
        )

        await runtime.reload_workflows(manual=True)

        refreshed = await runtime.workflow_loader.load_workflows(
            force_reload=True,
            target_global_id=target.global_id,
        )
        enabled_after = bool(refreshed[0].enabled) if refreshed else desired_enabled
        if enabled_after != desired_enabled:
            raise RuntimeError(
                f"Workflow lifecycle operation did not converge for '{target.global_id}'. "
                f"Expected enabled={desired_enabled}, got enabled={enabled_after}"
            )

        status = "enabled_now" if desired_enabled else "disabled_now"
        result = {
            "success": True,
            "operation": operation,
            "workflow_name": workflow_name,
            "global_id": target.global_id,
            "status": status,
            "enabled_before": enabled_before,
            "enabled_after": enabled_after,
            "message": f"Workflow '{target.global_id}' {'enabled' if desired_enabled else 'disabled'} successfully.",
        }
        logger.set_sinks(["validation"]).info(
            "workflow_lifecycle_changed",
            data={
                "operation": operation,
                "workflow_id": target.global_id,
                "status": status,
                "enabled_before": enabled_before,
                "enabled_after": enabled_after,
            },
        )
        return result

    @staticmethod
    def _resolve_enabled_state_from_frontmatter(*, file_path: str, fallback: bool) -> bool:
        """Read explicit enabled state from frontmatter.

        Missing `enabled` is treated as disabled for lifecycle/list semantics.
        If parsing fails, fallback preserves current behavior.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
        except OSError:
            return fallback

        if not content.startswith("---"):
            return fallback

        lines = content.splitlines()
        closing_index = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                closing_index = idx
                break

        if closing_index is None:
            return fallback

        enabled_pattern = re.compile(r"^\s*enabled\s*:\s*([^\n#]+)", re.IGNORECASE)
        for line in lines[1:closing_index]:
            match = enabled_pattern.match(line)
            if not match:
                continue
            value = match.group(1).strip().strip("'\"").lower()
            if value in {"true", "yes", "on", "1"}:
                return True
            if value in {"false", "no", "off", "0"}:
                return False
            return fallback

        # Missing key is treated as disabled for lifecycle/list operations.
        return False

    @staticmethod
    def _write_enabled_frontmatter(
        *,
        file_path: str,
        enabled: bool,
        vault_name: str,
        data_root: str,
    ) -> None:
        """Safely update only the enabled flag in workflow frontmatter."""
        workflows_root = os.path.realpath(
            os.path.join(data_root, vault_name, ASSISTANTMD_ROOT_DIR, WORKFLOW_DEFINITIONS_DIR)
        )
        target_real = os.path.realpath(file_path)
        if not (
            target_real == workflows_root
            or target_real.startswith(workflows_root + os.sep)
        ):
            raise ValueError("Workflow file path escapes vault workflow root")

        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()

        if not content.startswith("---"):
            raise ValueError("Workflow file must start with YAML frontmatter")

        lines = content.splitlines(keepends=True)
        closing_index = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                closing_index = idx
                break

        if closing_index is None:
            raise ValueError("Workflow file frontmatter is missing closing '---'")

        frontmatter_lines = lines[1:closing_index]
        replacement = "true" if enabled else "false"
        enabled_pattern = re.compile(r"^(\s*enabled\s*:\s*)([^\n#]*)(\s*(#.*)?)$", re.IGNORECASE)
        replaced = False
        for idx, line in enumerate(frontmatter_lines):
            line_no_newline = line.rstrip("\n")
            match = enabled_pattern.match(line_no_newline)
            if match:
                newline = "\n" if line.endswith("\n") else ""
                prefix = match.group(1)
                comment = match.group(3) or ""
                frontmatter_lines[idx] = f"{prefix}{replacement}{comment}{newline}"
                replaced = True
                break

        if not replaced:
            newline = "\n" if frontmatter_lines and frontmatter_lines[-1].endswith("\n") else "\n"
            frontmatter_lines.append(f"enabled: {replacement}{newline}")

        updated_content = "".join(lines[:1] + frontmatter_lines + lines[closing_index:])

        temp_path = f"{file_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            file.write(updated_content)
        os.replace(temp_path, file_path)
