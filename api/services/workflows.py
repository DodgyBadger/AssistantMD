"""Workflow lifecycle, authoring, history, and execution API services."""

import hashlib
from pathlib import Path
from typing import Any

from core.authoring.template_discovery import (
    list_system_workflow_templates,
)
from core.constants import ASSISTANTMD_ROOT_DIR
from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSnapshot,
    ExecutionTaskSource,
    workflow_vault_scope,
)
from core.runtime.paths import (
    get_system_root,
)
from core.runtime.state import RuntimeStateError, get_runtime_context
from core.scheduling.jobs import setup_scheduler_jobs
from core.tools.workflow_run import WorkflowRun
from core.utils.frontmatter import upsert_frontmatter_key
from core.vault_state.file_mutations import (
    replace_vault_file_content,
)
from core.workflow_runs import WorkflowRunRecord

from ..exceptions import SystemConfigurationError
from ..models import (
    ConfigurationError as APIConfigurationError,
)
from ..models import (
    SystemWorkflowTemplateSummary,
    WorkflowEnabledResponse,
    WorkflowFileResponse,
    WorkflowSummary,
)
from .execution_tasks import (
    _execution_task_info,
)
from .shared import (
    get_workflow_loader as _get_workflow_loader,
)
from .shared import logger


def get_workflow_run_history(global_id: str, *, limit: int = 50) -> dict[str, Any]:
    """Return durable workflow attempts in reverse chronological order."""
    clean_global_id = str(global_id or "").strip()
    if "/" not in clean_global_id:
        raise ValueError(
            f"Invalid global_id format. Expected 'vault/name', got: {clean_global_id}"
        )
    runtime = get_runtime_context()
    system_template_ids = {
        f"system/{template.name}"
        for template in get_system_workflow_template_summaries()
    }
    if clean_global_id in system_template_ids:
        runs = runtime.workflow_run_store.list_runs_by_workflow_name(
            clean_global_id,
            limit=limit,
        )
    else:
        runs = runtime.workflow_run_store.list_runs(clean_global_id, limit=limit)
    return {
        "workflow_id": clean_global_id,
        "runs": [run.to_dict() for run in runs],
    }


def _project_latest_workflow_runs(
    *,
    workflow_summaries: list[WorkflowSummary],
    system_workflow_templates: list[SystemWorkflowTemplateSummary],
    latest_runs: list[WorkflowRunRecord],
) -> dict[str, dict[str, Any]]:
    """Map vault workflows and cross-vault system templates to Dashboard rows."""
    workflow_ids = {summary.global_id for summary in workflow_summaries}
    system_template_ids = {
        f"system/{template.name}" for template in system_workflow_templates
    }
    projected: dict[str, dict[str, Any]] = {}
    for run in latest_runs:
        if run.workflow_id in workflow_ids:
            projected[run.workflow_id] = run.to_dict()
            continue
        if run.workflow_name in system_template_ids:
            projected.setdefault(run.workflow_name, run.to_dict())
    return projected


def get_workflow_summaries() -> list[WorkflowSummary]:
    """
    Get summary information about all loaded workflows.

    Returns:
        List of WorkflowSummary objects
    """
    summaries = []

    workflow_loader = _get_workflow_loader()
    all_workflows = getattr(workflow_loader, "_workflows", [])

    for workflow in all_workflows:
        if workflow.name.startswith("system/"):
            continue
        summary = WorkflowSummary(
            global_id=workflow.global_id,
            name=workflow.name,
            vault=workflow.vault,
            enabled=workflow.enabled,
            run_type=workflow.run_type,
            schedule_cron=workflow.schedule_string,
            description=workflow.description,
        )
        summaries.append(summary)

    return summaries


def get_system_workflow_template_summaries() -> list[SystemWorkflowTemplateSummary]:
    """Return packaged system workflow templates available to copy into a vault."""
    summaries = []

    for template in list_system_workflow_templates():
        frontmatter = template.frontmatter
        summaries.append(
            SystemWorkflowTemplateSummary(
                name=(
                    template.name[:-3]
                    if template.name.endswith(".md")
                    else template.name
                ),
                run_type=str(frontmatter.get("run_type") or "").strip().lower(),
                enabled=bool(frontmatter.get("enabled", False)),
                schedule_cron=str(frontmatter.get("schedule") or "").strip() or None,
                description=str(frontmatter.get("description") or "").strip(),
                path=str(template.path or ""),
            )
        )

    return sorted(summaries, key=lambda item: item.name.lower())


def get_workflow_file(global_id: str) -> WorkflowFileResponse:
    """Return editable source content for a vault workflow or system workflow template."""
    workflow_path, source = _resolve_workflow_file_path(global_id)
    content = workflow_path.read_text(encoding="utf-8")
    return WorkflowFileResponse(
        global_id=str(global_id or "").strip(),
        path=str(workflow_path),
        source=source,
        content=content,
        sha256=_sha256_text(content),
        message=None,
    )


async def update_workflow_file(
    global_id: str,
    *,
    content: str,
    expected_sha256: str | None = None,
) -> WorkflowFileResponse:
    """Replace workflow source content and reload workflow definitions."""
    normalized_id = str(global_id or "").strip()
    workflow_path, source = _resolve_workflow_file_path(global_id)
    current_content = workflow_path.read_text(encoding="utf-8")
    current_sha256 = _sha256_text(current_content)
    if expected_sha256 and expected_sha256 != current_sha256:
        raise ValueError(
            "Workflow file changed since it was opened. Refresh and retry."
        )

    if source == "vault":
        runtime = get_runtime_context()
        vault_name, _workflow_name = normalized_id.split("/", 1)
        vault_root = (Path(runtime.config.data_root) / vault_name).resolve()
        relative_path = workflow_path.relative_to(vault_root).as_posix()
        async with runtime.task_coordinator.track_current_task(
            kind=ExecutionTaskKind.WORKFLOW,
            scope=workflow_vault_scope(vault_name),
            source=ExecutionTaskSource.API,
            label=f"edit_workflow:{normalized_id}",
            metadata={
                "workflow_id": normalized_id,
                "vault": vault_name,
                "path": relative_path,
            },
        ):
            replace_vault_file_content(
                vault_path=vault_root,
                path=relative_path,
                content=content,
                operation="update_workflow_file",
                markdown_only=True,
            )
    else:
        _write_system_workflow_file_content(workflow_path, content)

    logger.info(
        "Workflow file updated",
        data={
            "global_id": normalized_id,
            "source": source,
            "path": str(workflow_path),
        },
    )

    try:
        runtime = get_runtime_context()
        await runtime.reload_workflows(manual=True)
    except RuntimeStateError:
        pass

    return WorkflowFileResponse(
        global_id=normalized_id,
        path=str(workflow_path),
        source=source,
        content=content,
        sha256=_sha256_text(content),
        message=f"Saved workflow '{normalized_id}'.",
    )


def _resolve_workflow_file_path(global_id: str) -> tuple[Path, str]:
    """Resolve an editable workflow ID to a file path under an allowed authoring root."""
    normalized_id = str(global_id or "").strip()
    if "/" not in normalized_id:
        raise ValueError(
            f"Invalid global_id format. Expected 'vault/name' or 'system/name', got: {global_id}"
        )

    if normalized_id.startswith("system/"):
        path = _resolve_system_workflow_file_path(normalized_id)
        return path, "system"

    runtime = get_runtime_context()
    workflow = runtime.workflow_loader.get_workflow_by_global_id(normalized_id)
    if workflow is None:
        raise ValueError(f"Workflow not found: {normalized_id}")

    data_root = Path(runtime.config.data_root).resolve()
    workflow_path = Path(workflow.file_path).resolve()
    vault_root = (data_root / workflow.vault).resolve()
    vault_authoring_root = (vault_root / ASSISTANTMD_ROOT_DIR / "Authoring").resolve()
    if not workflow_path.is_relative_to(vault_authoring_root):
        raise ValueError("Workflow path escapes vault Authoring root")
    if workflow_path.suffix.lower() != ".md":
        raise ValueError("Workflow editing only supports markdown authoring files")
    if not workflow_path.is_file():
        raise ValueError(f"Workflow file not found: {normalized_id}")
    return workflow_path, "vault"


def _write_system_workflow_file_content(path: Path, content: str) -> None:
    """Atomically replace a system workflow template file."""
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _resolve_system_workflow_file_path(global_id: str) -> Path:
    _system_prefix, template_name = global_id.split("/", 1)
    if not template_name or template_name.startswith("/") or ".." in template_name:
        raise ValueError("Invalid system workflow template name.")

    system_root = get_system_root()
    template = next(
        (
            record
            for record in list_system_workflow_templates(system_root)
            if (record.name[:-3] if record.name.endswith(".md") else record.name)
            == template_name
        ),
        None,
    )
    if template is None or not template.path:
        raise ValueError(f"System workflow template not found: {global_id}")

    template_path = Path(template.path).resolve()
    system_authoring_root = (system_root / "Authoring").resolve()
    if not template_path.is_relative_to(system_authoring_root):
        raise ValueError("System workflow template path escapes system Authoring root")
    if template_path.suffix.lower() != ".md":
        raise ValueError(
            "System workflow editing only supports markdown authoring files"
        )
    if not template_path.is_file():
        raise ValueError(f"System workflow template file not found: {global_id}")
    return template_path


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def set_workflow_enabled_state(
    global_id: str, enabled: bool
) -> WorkflowEnabledResponse:
    """Set one workflow or system workflow template enabled flag."""
    normalized_id = str(global_id or "").strip()
    if "/" not in normalized_id:
        raise ValueError(
            f"Invalid global_id format. Expected 'vault/name' or 'system/name', got: {global_id}"
        )

    if normalized_id.startswith("system/"):
        return await _set_system_workflow_enabled_state(normalized_id, enabled)

    vault_name, workflow_name = normalized_id.split("/", 1)
    if not vault_name or not workflow_name:
        raise ValueError(
            f"Invalid global_id format. Expected 'vault/name', got: {global_id}"
        )

    operation = "enable_workflow" if enabled else "disable_workflow"
    result = await WorkflowRun._set_workflow_enabled_state(
        operation=operation,
        vault_name=vault_name,
        workflow_name=workflow_name,
    )
    if not result.get("success"):
        raise ValueError(
            str(result.get("message") or f"Workflow not found: {normalized_id}")
        )

    return WorkflowEnabledResponse(
        success=True,
        global_id=normalized_id,
        enabled_before=bool(result.get("enabled_before", False)),
        enabled_after=bool(result.get("enabled_after", enabled)),
        message=str(result.get("message") or f"Workflow '{normalized_id}' updated."),
    )


async def _set_system_workflow_enabled_state(
    global_id: str, enabled: bool
) -> WorkflowEnabledResponse:
    """Set enabled frontmatter on a system workflow template."""
    template_path = _resolve_system_workflow_file_path(global_id)
    template_content = template_path.read_text(encoding="utf-8")
    template_frontmatter = next(
        (
            record.frontmatter
            for record in list_system_workflow_templates(get_system_root())
            if Path(record.path or "").resolve() == template_path
        ),
        {},
    )

    enabled_before = _coerce_frontmatter_enabled(template_frontmatter)
    content = template_content
    updated_content = upsert_frontmatter_key(
        content,
        key="enabled",
        value="true" if enabled else "false",
    )
    _write_system_workflow_file_content(template_path, updated_content)

    logger.info(
        "System workflow template enabled state changed",
        data={
            "global_id": global_id,
            "enabled_before": enabled_before,
            "enabled_after": enabled,
        },
    )

    try:
        runtime = get_runtime_context()
        await runtime.reload_workflows(manual=True)
    except RuntimeStateError:
        pass

    return WorkflowEnabledResponse(
        success=True,
        global_id=global_id,
        enabled_before=enabled_before,
        enabled_after=enabled,
        message=f"Workflow '{global_id}' {'enabled' if enabled else 'disabled'} successfully.",
    )


def _coerce_frontmatter_enabled(frontmatter: dict[str, Any]) -> bool:
    value = frontmatter.get("enabled")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "on", "1"}
    return False


def get_configuration_errors() -> list[APIConfigurationError]:
    """Get configuration errors from the workflow loader."""
    # Get errors from workflow loader
    core_errors = _get_workflow_loader().get_configuration_errors()

    # Convert to API models
    api_errors = []
    for error in core_errors:
        api_error = APIConfigurationError(
            vault=error.vault,
            workflow_name=error.workflow_name,
            file_path=error.file_path,
            error_message=error.error_message,
            error_type=error.error_type,
            timestamp=error.timestamp,
        )
        api_errors.append(api_error)

    return api_errors


async def rescan_vaults_and_update_scheduler(
    scheduler: Any | None = None,
) -> dict[str, Any]:
    """
    Force rediscovery of vault directories and reload workflow configurations.
    Updates scheduler jobs based on new configurations.

    Args:
        scheduler: APScheduler instance (optional, will try to get from main if None)

    Returns:
        Dictionary with rescan statistics

    Raises:
        SystemConfigurationError: If rescan or scheduler update fails
    """
    try:
        # Prefer the runtime reload path so workflow and vault-state refresh
        # behavior stays centralized.
        try:
            runtime = get_runtime_context()
            results = await runtime.reload_workflows(manual=True)
        except RuntimeStateError:
            if scheduler is None:
                scheduler = None
            results = await setup_scheduler_jobs(scheduler, manual_reload=True)

        logger.info(
            "Vault rescan completed",
            data={
                "vaults_discovered": results.get("vaults_discovered"),
                "workflows_loaded": results.get("workflows_loaded"),
                "enabled_workflows": results.get("enabled_workflows"),
                "scheduler_jobs_synced": results.get("scheduler_jobs_synced"),
            },
        )

        return results

    except Exception as e:
        error_msg = f"Failed to rescan vaults and update scheduler: {str(e)}"
        raise SystemConfigurationError(error_msg) from e


async def execute_workflow_manually(
    global_id: str,
    expect_failure: bool = False,
    *,
    vault_name: str | None = None,
) -> dict[str, Any]:
    """
    Start a specific workflow manually.

    Args:
        global_id: Workflow global ID in format "vault/name"
        expect_failure: Whether workflow-level failures are expected (validation hint)

    Returns:
        Dictionary with execution task information

    Raises:
        SystemConfigurationError: If workflow not found or execution fails
        ValueError: If global_id format is invalid
    """
    try:
        logger.info(
            "Workflow execution started",
            data={
                "global_id": global_id,
                "vault_name": vault_name or "",
            },
        )

        executable_global_id = _normalize_manual_workflow_global_id(
            global_id=global_id,
            vault_name=vault_name,
        )

        try:
            runtime = get_runtime_context()
            task = await runtime.workflow_governor.start_workflow(
                global_id=executable_global_id,
                source=ExecutionTaskSource.API,
                expect_failure=expect_failure,
                background_tasks=runtime.background_tasks,
            )
        except Exception as workflow_error:
            if isinstance(workflow_error, ValueError):
                raise
            raise SystemConfigurationError(
                f"Workflow execution failed for '{global_id}': {str(workflow_error)}"
            ) from workflow_error

        logger.info(
            "Workflow execution started",
            data={
                "global_id": global_id,
                "executable_global_id": executable_global_id,
                "task_id": task.task_id,
                "status": task.status,
            },
        )
        return _workflow_started_response(global_id=global_id, task=task)

    except (ValueError, SystemConfigurationError):
        raise  # Re-raise known errors
    except Exception as e:
        error_msg = f"Failed to execute workflow '{global_id}': {str(e)}"
        raise SystemConfigurationError(error_msg) from e


def _workflow_started_response(
    *,
    global_id: str,
    task: ExecutionTaskSnapshot,
) -> dict[str, Any]:
    """Build the API response for an accepted manual workflow run."""
    return {
        "success": True,
        "global_id": global_id,
        "status": task.status,
        "task": _execution_task_info(task).model_dump(mode="python"),
        "message": f"Workflow '{global_id}' started as task {task.task_id}.",
    }


def _normalize_manual_workflow_global_id(
    *,
    global_id: str,
    vault_name: str | None,
) -> str:
    """Resolve public manual workflow IDs to governor-executable workflow IDs."""
    if "/" not in global_id:
        raise ValueError(
            f"Invalid global_id format. Expected 'vault/name' or 'system/name', got: {global_id}"
        )

    normalized_id = str(global_id or "").strip()
    if not normalized_id.startswith("system/"):
        return normalized_id

    if not vault_name:
        raise ValueError("vault_name is required to run a system workflow template.")

    template_name = normalized_id.split("/", 1)[1]
    if not template_name or template_name.startswith("/") or ".." in template_name:
        raise ValueError("Invalid system workflow template name.")

    runtime = get_runtime_context()
    vault_path = Path(runtime.config.data_root) / vault_name
    if not vault_path.exists() or not vault_path.is_dir():
        raise ValueError(f"Vault not found: {vault_name}")

    template_exists = any(
        (record.name[:-3] if record.name.endswith(".md") else record.name)
        == template_name
        for record in list_system_workflow_templates(runtime.config.system_root)
    )
    if not template_exists:
        raise ValueError(f"System workflow template not found: {normalized_id}")

    return f"{vault_name}/system/{template_name}"
