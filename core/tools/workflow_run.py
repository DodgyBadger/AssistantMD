"""Authoring run tool for vault-scoped discovery and execution."""

from __future__ import annotations

import traceback
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic_ai.tools import Tool

from core.authoring.contracts import AssembleContextResult, ContextMessage
from core.authoring.service import run_authoring_template
from core.authoring.template_discovery import discover_workflow_files
from core.logger import UnifiedLogger
from core.runtime.state import RuntimeStateError, get_runtime_context
from core.scheduling.jobs import create_job_args
from core.constants import ASSISTANTMD_ROOT_DIR, AUTHORING_DIR
from core.utils.frontmatter import parse_simple_frontmatter, upsert_frontmatter_key
from .base import BaseTool


logger = UnifiedLogger(tag="workflow-run-tool")


class WorkflowRun(BaseTool):
    """Run authored automations in the current vault and list available names."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the workflow run tool bound to the current vault path."""

        async def workflow_run(
            *,
            operation: str,
            workflow_name: str = "",
            step_name: str = "",
        ) -> str:
            """Run or list authored automations in the current vault.

            :param operation: Operation name (list, run, enable_workflow, disable_workflow)
            :param workflow_name: Workflow name relative to AssistantMD/Authoring (required for run/enable/disable)
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
                    name, error = cls._resolve_valid_workflow_name(op, workflow_name)
                    if error:
                        return error

                    global_id = f"{vault_name}/{name}"
                    single_step = (step_name or "").strip() or None
                    try:
                        result = await cls._execute_authoring_artifact(
                            vault_path=vault_path,
                            vault_name=vault_name,
                            workflow_name=name,
                            step_name=single_step,
                        )
                        return cls._format_run_result(result)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error(
                            "workflow_run execution failed",
                            data={
                                "operation": op,
                                "global_id": global_id,
                                "step_name": single_step,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                                "traceback": traceback.format_exc(),
                            },
                        )
                        return cls._format_run_error(global_id, single_step, exc)

                if op in {"enable_workflow", "disable_workflow"}:
                    name, error = cls._resolve_valid_workflow_name(op, workflow_name)
                    if error:
                        return error
                    file_path = cls._resolve_workflow_file_path(vault_path=vault_path, workflow_name=name)
                    if file_path.exists():
                        run_type = cls._read_run_type(file_path)
                        if run_type == "context":
                            return (
                                f"Lifecycle operation '{op}' is only supported for run_type='workflow'. "
                                f"'{name}' is run_type='context'."
                            )
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
                logger.error(
                    "workflow_run operation failed",
                    data={
                        "operation": operation,
                        "workflow_name": workflow_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                return f"Error performing '{operation}' operation: {exc}"

        return Tool(
            workflow_run,
            name="workflow_run",
            description="List authored automations in the current vault and run, enable, or disable them.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for workflow execution."""
        return """
Full documentation:
- `__virtual_docs__/tools/workflow_run.md`
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
            f"{ASSISTANTMD_ROOT_DIR}/{AUTHORING_DIR}/",
            f"{AUTHORING_DIR}/",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break

        if normalized.endswith(".md"):
            normalized = normalized[:-3]

        return normalized.strip("/")

    @classmethod
    def _resolve_valid_workflow_name(
        cls,
        operation: str,
        workflow_name: str,
    ) -> tuple[str, str | None]:
        normalized = cls._normalize_workflow_name_input(workflow_name)
        if not normalized:
            return "", f"workflow_name is required for operation='{operation}'."
        if "/app/data/" in normalized:
            return "", (
                "Invalid workflow_name. Runtime filesystem roots are not allowed; "
                "pass vault-internal workflow names from workflow_run(operation=\"list\")."
            )
        if cls._is_invalid_workflow_name(normalized):
            return "", (
                "Invalid workflow_name. Use a vault-relative name "
                "(e.g. 'daily' or 'folder/daily') without '..'."
            )
        return normalized, None

    @staticmethod
    async def _list_workflows(vault_name: str) -> str:
        runtime = get_runtime_context()
        vault_path = str(Path(runtime.config.data_root) / vault_name)
        workflow_files = discover_workflow_files(vault_path)

        if not workflow_files:
            return f"No authored automations found for vault '{vault_name}'."

        lines = [f"Authored automations in vault '{vault_name}':"]
        artifacts = []
        for file_path in workflow_files:
            artifact_name = WorkflowRun._workflow_name_from_file_path(vault_path=vault_path, file_path=file_path)
            if not artifact_name:
                continue
            path_obj = Path(file_path)
            try:
                frontmatter, _ = parse_simple_frontmatter(path_obj.read_text(encoding="utf-8"), require_frontmatter=False)
                run_type = WorkflowRun._normalize_run_type(frontmatter)
                description = str(frontmatter.get("description") or "").strip() or "(no description)"
                enabled_display = (
                    WorkflowRun._resolve_enabled_state_from_frontmatter(file_path=file_path, fallback=False)
                    if run_type == "workflow"
                    else "n/a"
                )
                artifacts.append((artifact_name, run_type, description, enabled_display))
            except Exception as exc:  # pylint: disable=broad-except
                artifacts.append((artifact_name, "invalid", f"Failed to parse frontmatter: {exc}", "n/a"))

        if not artifacts:
            return f"No authored automations found for vault '{vault_name}'."

        for artifact_name, run_type, description, enabled_display in sorted(artifacts, key=lambda item: item[0].lower()):
            lines.append(
                f"- workflow_name: {artifact_name} | workflow_id: {vault_name}/{artifact_name} | run_type: {run_type} | enabled: {enabled_display} | description: {description}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_run_result(result: dict) -> str:
        lines = [
            f"success: {result.get('success', False)}",
            f"global_id: {result.get('global_id', '')}",
            f"run_type: {result.get('run_type', '')}",
            f"execution_time_seconds: {result.get('execution_time_seconds', 0)}",
        ]
        if result.get("status") is not None:
            lines.append(f"status: {result.get('status', '')}")
        if result.get("reason"):
            lines.append(f"reason: {result.get('reason', '')}")
        if result.get("message"):
            lines.append(f"message: {result.get('message', '')}")
        extra_lines = result.get("details", [])
        if extra_lines:
            lines.append("details:")
            lines.extend([f"- {line}" for line in extra_lines])
        return "\n".join(lines)

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

    @classmethod
    async def _execute_authoring_artifact(
        cls,
        *,
        vault_path: str,
        vault_name: str,
        workflow_name: str,
        step_name: str | None,
    ) -> dict[str, Any]:
        file_path = cls._resolve_workflow_file_path(vault_path=vault_path, workflow_name=workflow_name)
        if not file_path.exists():
            raise ValueError(f"Workflow file not found: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"Workflow path is not a file: {file_path}")

        run_type = cls._read_run_type(file_path)
        if run_type == "context":
            return await cls._execute_context_template(
                vault_name=vault_name,
                workflow_name=workflow_name,
                file_path=file_path,
            )

        global_id = f"{vault_name}/{workflow_name}"
        result = await cls._execute_workflow(global_id, step_name)
        result["run_type"] = "workflow"
        return result

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
        job_args = create_job_args(target.global_id, file_path=target.file_path)
        execution_result = await target.workflow_function(job_args, **kwargs)
        elapsed = (datetime.now() - started).total_seconds()
        terminal_status = str(getattr(execution_result, "status", "completed") or "completed")
        terminal_reason = str(getattr(execution_result, "reason", "") or "")

        return {
            "success": True,
            "global_id": target.global_id,
            "run_type": "workflow",
            "status": terminal_status,
            "execution_time_seconds": elapsed,
            "output_files": [],
            "reason": terminal_reason or None,
            "details": [],
            "message": (
                f"Workflow '{target.global_id}' {terminal_status} in {elapsed:.2f} seconds"
                + (f": {terminal_reason}" if terminal_reason else "")
            ),
        }

    @classmethod
    async def _execute_context_template(
        cls,
        *,
        vault_name: str,
        workflow_name: str,
        file_path: Path,
    ) -> dict[str, Any]:
        global_id = f"{vault_name}/{workflow_name}"
        started = datetime.now()
        execution_result = await run_authoring_template(
            workflow_id=f"{vault_name}/context/{workflow_name}",
            file_path=str(file_path),
        )
        elapsed = (datetime.now() - started).total_seconds()
        details = cls._summarize_context_execution(execution_result.value)
        return {
            "success": True,
            "global_id": global_id,
            "run_type": "context",
            "status": execution_result.status,
            "execution_time_seconds": elapsed,
            "reason": execution_result.reason or None,
            "details": details,
            "message": (
                f"Context template '{global_id}' dry-run {execution_result.status} in {elapsed:.2f} seconds"
                + (f": {execution_result.reason}" if execution_result.reason else "")
            ),
        }

    @staticmethod
    def _resolve_workflow_file_path(*, vault_path: str, workflow_name: str) -> Path:
        normalized = workflow_name.strip().replace("\\", "/")
        candidate = Path(vault_path) / ASSISTANTMD_ROOT_DIR / AUTHORING_DIR / normalized
        if candidate.suffix.lower() != ".md":
            candidate = candidate.with_suffix(".md")
        return candidate

    @staticmethod
    def _workflow_name_from_file_path(*, vault_path: str, file_path: str) -> str:
        authoring_root = Path(vault_path) / ASSISTANTMD_ROOT_DIR / AUTHORING_DIR
        return Path(file_path).relative_to(authoring_root).with_suffix("").as_posix()

    @staticmethod
    def _normalize_run_type(frontmatter: dict[str, Any]) -> str:
        raw = str(frontmatter.get("run_type") or "").strip().lower()
        return raw if raw in {"workflow", "context"} else "workflow"

    @classmethod
    def _read_run_type(cls, file_path: Path) -> str:
        frontmatter, _ = parse_simple_frontmatter(file_path.read_text(encoding="utf-8"), require_frontmatter=False)
        return cls._normalize_run_type(frontmatter)

    @staticmethod
    def _summarize_context_execution(value: Any) -> list[str]:
        assembled = WorkflowRun._normalize_context_result(value)
        messages = tuple(assembled.messages or ())
        instructions = tuple(assembled.instructions or ())
        roles = [message.role for message in messages if getattr(message, "role", None)]
        details = [
            "assembled_context: True",
            f"message_count: {len(messages)}",
            f"instruction_count: {len(instructions)}",
        ]
        if roles:
            details.append(f"message_roles: {', '.join(roles)}")
        if instructions:
            details.append("instructions_present: True")
        return details

    @staticmethod
    def _normalize_context_result(value: Any) -> AssembleContextResult:
        if isinstance(value, AssembleContextResult):
            return value
        if isinstance(value, dict):
            messages = value.get("messages", ())
            instructions = value.get("instructions", ())
            if not isinstance(messages, (list, tuple)):
                raise ValueError("Context template dry-run returned invalid 'messages' data")
            if not isinstance(instructions, (list, tuple)):
                raise ValueError("Context template dry-run returned invalid 'instructions' data")
            normalized_messages: list[ContextMessage] = []
            for item in messages:
                if isinstance(item, ContextMessage):
                    normalized_messages.append(item)
                    continue
                if isinstance(item, dict):
                    normalized_messages.append(
                        ContextMessage(
                            role=str(item.get("role") or "system"),
                            content=str(item.get("content") or ""),
                            metadata=dict(item.get("metadata") or {}),
                        )
                    )
                    continue
                raise ValueError("Context template dry-run returned an unsupported message item")
            normalized_instructions = tuple(str(item).strip() for item in instructions if str(item).strip())
            return AssembleContextResult(
                messages=tuple(normalized_messages),
                instructions=normalized_instructions,
            )
        raise ValueError("Context template dry-run must return AssembleContextResult or equivalent dict")

    @classmethod
    async def _set_workflow_enabled_state(
        cls,
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
            cls._emit_lifecycle_event(
                operation=operation,
                workflow_id=attempted_global_id,
                status=status,
            )
            return cls._build_lifecycle_result(
                success=False,
                operation=operation,
                workflow_name=workflow_name,
                global_id=attempted_global_id,
                status=status,
                enabled_before=None,
                enabled_after=None,
                message=f"Workflow not found: {attempted_global_id}",
            )

        enabled_before = cls._resolve_enabled_state_from_frontmatter(
            file_path=target.file_path,
            fallback=bool(target.enabled),
        )
        if enabled_before == desired_enabled:
            status = "already_enabled" if desired_enabled else "already_disabled"
            cls._emit_lifecycle_event(
                operation=operation,
                workflow_id=target.global_id,
                status=status,
                enabled_before=enabled_before,
                enabled_after=enabled_before,
            )
            return cls._build_lifecycle_result(
                success=True,
                operation=operation,
                workflow_name=workflow_name,
                global_id=target.global_id,
                status=status,
                enabled_before=enabled_before,
                enabled_after=enabled_before,
                message=f"Workflow '{target.global_id}' is already {'enabled' if desired_enabled else 'disabled'}.",
            )

        cls._write_enabled_frontmatter(
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
        cls._emit_lifecycle_event(
            operation=operation,
            workflow_id=target.global_id,
            status=status,
            enabled_before=enabled_before,
            enabled_after=enabled_after,
        )
        return cls._build_lifecycle_result(
            success=True,
            operation=operation,
            workflow_name=workflow_name,
            global_id=target.global_id,
            status=status,
            enabled_before=enabled_before,
            enabled_after=enabled_after,
            message=f"Workflow '{target.global_id}' {'enabled' if desired_enabled else 'disabled'} successfully.",
        )

    @staticmethod
    def _build_lifecycle_result(
        *,
        success: bool,
        operation: str,
        workflow_name: str,
        global_id: str,
        status: str,
        enabled_before: bool | None,
        enabled_after: bool | None,
        message: str,
    ) -> dict:
        return {
            "success": success,
            "operation": operation,
            "workflow_name": workflow_name,
            "global_id": global_id,
            "status": status,
            "enabled_before": "" if enabled_before is None else enabled_before,
            "enabled_after": "" if enabled_after is None else enabled_after,
            "message": message,
        }

    @staticmethod
    def _emit_lifecycle_event(
        *,
        operation: str,
        workflow_id: str,
        status: str,
        enabled_before: bool | None = None,
        enabled_after: bool | None = None,
    ) -> None:
        payload = {
            "operation": operation,
            "workflow_id": workflow_id,
            "status": status,
        }
        if enabled_before is not None:
            payload["enabled_before"] = enabled_before
        if enabled_after is not None:
            payload["enabled_after"] = enabled_after
        logger.set_sinks(["validation"]).info(
            "workflow_lifecycle_changed",
            data=payload,
        )

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

        try:
            properties, _ = parse_simple_frontmatter(content, require_frontmatter=False)
        except ValueError:
            return fallback

        enabled_value = properties.get("enabled")
        if isinstance(enabled_value, bool):
            return enabled_value
        if isinstance(enabled_value, str):
            normalized = enabled_value.strip().lower()
            if normalized in {"true", "yes", "on", "1"}:
                return True
            if normalized in {"false", "no", "off", "0"}:
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
        assistantmd_root = os.path.realpath(
            os.path.join(data_root, vault_name, ASSISTANTMD_ROOT_DIR)
        )
        target_real = os.path.realpath(file_path)
        if not target_real.startswith(assistantmd_root + os.sep):
            raise ValueError("Workflow file path escapes vault AssistantMD root")

        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()

        updated_content = upsert_frontmatter_key(
            content,
            key="enabled",
            value="true" if enabled else "false",
        )

        temp_path = f"{file_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            file.write(updated_content)
        os.replace(temp_path, file_path)
