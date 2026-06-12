"""
Service layer for API operations.
Handles business logic for status reporting, vault management, etc.
"""

import asyncio
import contextvars
import json
import hashlib
import mimetypes
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import List, Optional, Dict, Any

import yaml
from sqlalchemy import func, select

from core.authoring.service import run_authoring_template
from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context, RuntimeStateError
from core.scheduling.jobs import setup_scheduler_jobs
from core.scheduling.job_history import get_scheduler_job_history
from core.scheduling.system_jobs import SYSTEM_JOB_IDS
from core.settings.store import (
    get_models_config,
    get_tools_config,
    get_providers_config,
    get_active_settings_path,
    SETTINGS_TEMPLATE,
    get_general_settings,
)
from core.runtime.paths import set_bootstrap_roots, resolve_bootstrap_data_root, resolve_bootstrap_system_root
from core.settings import (
    validate_settings,
    SettingsError,
)
from core.settings.config_editor import (
    delete_model_mapping,
    delete_provider_config,
    list_general_settings,
    update_general_setting,
    upsert_model_mapping,
    upsert_provider_config,
)
from core.runtime.reload_service import reload_configuration
from core.settings.secrets_store import (
    list_secret_entries,
    set_secret_value,
    remove_secret,
    delete_secret,
    secret_has_value,
)
from core.runtime.paths import get_system_root
from core.authoring.cache import purge_expired_cache_artifacts
from core.chat import ChatStore, export_chat_transcript, remove_chat_transcript_exports
from core.chat.chat_store import StoredChatSession
from core.chat.compaction import compact_chat_history, get_compaction_status
from core.memory.session_summary import SessionSummaryStore
from core.system_migrations import (
    get_system_migration_status as get_registered_system_migration_status,
    run_system_migrations as run_registered_system_migrations,
)
from core.vector import VectorService
from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSource,
    chat_session_scope,
    compaction_task_label,
    workflow_vault_scope,
)
from core.vault_state.service import VaultStateService
from core.vault_state.cleanup import cleanup_expired_vault_state
from core.vault_state.file_mutations import replace_vault_file_content
from core.vault_state.models import VaultFile, VaultFileEvent
from .models import (
    VaultInfo,
    SchedulerInfo,
    SystemInfo,
    StatusResponse,
    WorkflowEnabledResponse,
    WorkflowFileResponse,
    WorkflowSummary,
    SystemWorkflowTemplateSummary,
    ConfigurationError as APIConfigurationError,
    ModelInfo,
    ToolInfo,
    MetadataResponse,
    ConfigurationStatusInfo,
    ConfigurationIssueInfo,
    ProviderInfo,
    ModelConfigRequest,
    ProviderConfigRequest,
    CachePurgeResponse,
    SystemTemplateSeedResponse,
    SystemMigrationRunResponse,
    SystemMigrationStatusResponse,
    SystemMigrationTargetInfo,
    OperationResult,
    SecretInfo,
    SecretUpdateRequest,
    SettingInfo,
    SettingUpdateRequest,
    SystemLogResponse,
    SystemSettingsResponse,
    TemplateInfo,
    ChatSessionInfo,
    ChatSessionForkResponse,
    ChatWorkspaceInfo,
    ChatSessionDetailResponse,
    ChatSessionFailureInfo,
    ChatSessionMessageInfo,
    ChatSessionToolEventInfo,
    VaultDirectoryInfo,
    VaultDirectoryListResponse,
    ChatSessionExportResponse,
    ChatHistoryCompactionResponse,
    ChatHistoryCompactionStatusResponse,
    ChatSessionsPurgeResponse,
    ExecutionTaskCancelResponse,
    ExecutionTaskInfo,
    ExecutionTaskListResponse,
    VaultTaskMutationGroupInfo,
    VaultTaskMutationInfo,
    VaultTaskMutationsResponse,
    VaultStateCleanupResponse,
)
from .exceptions import APIException, SystemConfigurationError
from .utils import generate_session_id
from core.constants import ASSISTANTMD_ROOT_DIR, IMPORT_DIR
from core.ingestion.models import SourceKind, JobStatus
from core.ingestion.service import IngestionService
from core.ingestion.registry import importer_registry
from core.ingestion.jobs import find_job_for_source
from core.ingestion.task_execution import process_ingestion_job_in_task
from core.authoring.template_discovery import (
    list_templates,
    list_system_workflow_templates,
    seed_system_templates,
)
from core.tools.workflow_run import WorkflowRun
from core.utils.frontmatter import upsert_frontmatter_key

# Create API services logger
logger = UnifiedLogger(tag="api-services")
_chat_store = ChatStore()

# Global variable to track system startup time
_system_startup_time: Optional[datetime] = None


class ChatSessionVaultMismatch(ValueError):
    """Raised when an existing chat session is requested under another vault."""

    def __init__(self, *, session_id: str, requested_vault: str, bound_vault: str):
        self.session_id = session_id
        self.requested_vault = requested_vault
        self.bound_vault = bound_vault
        super().__init__(
            f"Chat session '{session_id}' belongs to vault '{bound_vault}', "
            f"not vault '{requested_vault}'."
        )


@dataclass(frozen=True)
class SnapshotFileResponse:
    """Resolved snapshot artifact for HTTP serving."""

    path: Path
    filename: str
    media_type: str


def resolve_chat_session_for_request(*, requested_session_id: str | None, vault_name: str) -> str:
    """Return a session ID that is durably bound to the requested vault."""
    session_id = (requested_session_id or "").strip()
    if session_id:
        existing_session = _chat_store.get_session_by_id(session_id)
        if existing_session is not None:
            if existing_session.vault_name != vault_name:
                logger.warning(
                    "Rejected chat session vault mismatch",
                    data={
                        "session_id": session_id,
                        "requested_vault": vault_name,
                        "bound_vault": existing_session.vault_name,
                    },
                )
                raise ChatSessionVaultMismatch(
                    session_id=session_id,
                    requested_vault=vault_name,
                    bound_vault=existing_session.vault_name,
                )
            _chat_store.ensure_session(session_id=session_id, vault_name=vault_name)
            return session_id
        _chat_store.ensure_session(session_id=session_id, vault_name=vault_name)
        return session_id

    base_session_id = generate_session_id(vault_name)
    generated_session_id = base_session_id
    suffix = 1
    while _chat_store.get_session_by_id(generated_session_id) is not None:
        suffix += 1
        generated_session_id = f"{base_session_id}_{suffix}"
    _chat_store.ensure_session(session_id=generated_session_id, vault_name=vault_name)
    return generated_session_id


def _chat_workspace_info(path: str | None) -> ChatWorkspaceInfo | None:
    normalized = (path or "").strip()
    if not normalized:
        return None
    return ChatWorkspaceInfo(path=normalized, exists=True)


def _normalize_workspace_path(path: str | None) -> str:
    """Normalize a safe vault-relative workspace path string."""
    raw_path = (path or "").strip().replace("\\", "/")
    if not raw_path:
        return ""
    if raw_path.startswith("/"):
        raise APIException(
            status_code=400,
            error_type="InvalidWorkspacePath",
            message="Workspace path must be relative to the vault.",
            details={"path": path},
        )
    parts = [part for part in raw_path.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise APIException(
            status_code=400,
            error_type="InvalidWorkspacePath",
            message="Workspace path cannot contain '..'.",
            details={"path": path},
        )
    return Path(*parts).as_posix() if parts else ""


def _resolve_existing_vault_directory(*, vault_name: str, path: str | None) -> tuple[str, Path]:
    """Return a normalized path and existing directory for picker browsing."""
    normalized_path = _normalize_workspace_path(path)
    runtime = get_runtime_context()
    vault_root = (runtime.config.data_root / vault_name).resolve()
    if not vault_root.is_dir():
        raise APIException(
            status_code=404,
            error_type="VaultNotFound",
            message=f"Vault not found: {vault_name}",
            details={"vault_name": vault_name},
        )
    resolved = (vault_root / normalized_path).resolve() if normalized_path else vault_root
    try:
        resolved.relative_to(vault_root)
    except ValueError as exc:
        raise APIException(
            status_code=400,
            error_type="InvalidWorkspacePath",
            message="Workspace path escapes the vault.",
            details={"path": path, "vault_name": vault_name},
        ) from exc
    if not resolved.exists():
        raise APIException(
            status_code=404,
            error_type="WorkspaceNotFound",
            message=f"Workspace directory not found: {normalized_path}",
            details={"path": normalized_path, "vault_name": vault_name},
        )
    if not resolved.is_dir():
        raise APIException(
            status_code=400,
            error_type="WorkspaceNotDirectory",
            message=f"Workspace path is not a directory: {normalized_path}",
            details={"path": normalized_path, "vault_name": vault_name},
        )
    return normalized_path, resolved


def list_vault_directories(vault_name: str, path: str | None = None) -> VaultDirectoryListResponse:
    """Return child directories for one vault-relative path."""
    base_path, base_dir = _resolve_existing_vault_directory(vault_name=vault_name, path=path)
    runtime = get_runtime_context()
    vault_root = (runtime.config.data_root / vault_name).resolve()
    directories: list[VaultDirectoryInfo] = []
    for child in sorted(base_dir.iterdir(), key=lambda item: item.name.lower()):
        if not _is_workspace_picker_directory(child):
            continue
        try:
            relative = child.resolve().relative_to(vault_root).as_posix()
        except ValueError:
            continue
        has_children = any(_is_workspace_picker_directory(grandchild) for grandchild in child.iterdir())
        directories.append(
            VaultDirectoryInfo(
                name=child.name,
                path=relative,
                has_children=has_children,
            )
        )
    return VaultDirectoryListResponse(path=base_path, directories=directories)


def _is_workspace_picker_directory(path: Path) -> bool:
    """Return whether a directory should appear in the workspace picker."""
    return path.is_dir() and not path.name.startswith(".") and path.name != ASSISTANTMD_ROOT_DIR


def set_chat_session_workspace(vault_name: str, session_id: str, path: str | None) -> ChatWorkspaceInfo | None:
    """Set or clear the workspace path for one chat session."""
    normalized_path = _normalize_workspace_path(path)
    existing_session = _chat_store.get_session_by_id(session_id)
    if existing_session is None:
        raise APIException(
            status_code=404,
            error_type="ChatSessionNotFound",
            message=f"Chat session not found: {session_id}",
            details={"session_id": session_id, "vault_name": vault_name},
        )
    if existing_session.vault_name != vault_name:
        raise APIException(
            status_code=409,
            error_type="ChatSessionVaultMismatch",
            message=(
                f"Chat session '{session_id}' belongs to vault '{existing_session.vault_name}' "
                f"and cannot be used with vault '{vault_name}'."
            ),
            details={
                "session_id": session_id,
                "requested_vault": vault_name,
                "bound_vault": existing_session.vault_name,
            },
        )
    _chat_store.set_session_workspace(
        session_id=session_id,
        vault_name=vault_name,
        workspace_path=normalized_path or None,
    )
    logger.info(
        "Chat session workspace updated",
        data={
            "vault_name": vault_name,
            "session_id": session_id,
            "workspace_path": normalized_path,
            "workspace_set": bool(normalized_path),
        },
    )
    return _chat_workspace_info(normalized_path)


def _execution_task_info(snapshot) -> ExecutionTaskInfo:
    """Convert a runtime task snapshot into an API model."""
    return ExecutionTaskInfo(
        task_id=snapshot.task_id,
        kind=snapshot.kind,
        scope=snapshot.scope,
        source=snapshot.source,
        label=snapshot.label,
        status=snapshot.status,
        created_at=snapshot.created_at,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        cancel_requested=snapshot.cancel_requested,
        terminal_reason=snapshot.terminal_reason,
        latest_event=snapshot.latest_event,
        metadata=dict(snapshot.metadata or {}),
    )


async def list_execution_tasks(
    *,
    kind: str | None = None,
    scope: str | None = None,
    include_terminal: bool = True,
) -> ExecutionTaskListResponse:
    """List process-local execution task snapshots."""
    runtime = get_runtime_context()
    snapshots = await runtime.task_coordinator.list_tasks(
        kind=kind,
        scope=scope,
        include_terminal=include_terminal,
    )
    return ExecutionTaskListResponse(tasks=[_execution_task_info(item) for item in snapshots])


async def get_execution_task(task_id: str) -> ExecutionTaskInfo:
    """Return one process-local execution task snapshot."""
    runtime = get_runtime_context()
    snapshot = await runtime.task_coordinator.get_task(task_id)
    if snapshot is None:
        raise APIException(
            status_code=404,
            error_type="ExecutionTaskNotFound",
            message=f"Execution task not found: {task_id}",
            details={"task_id": task_id},
        )
    return _execution_task_info(snapshot)


async def cancel_execution_task(task_id: str) -> ExecutionTaskCancelResponse:
    """Request cancellation for one process-local execution task."""
    runtime = get_runtime_context()
    cancellation = await runtime.task_coordinator.cancel_task(task_id)
    if cancellation is None:
        raise APIException(
            status_code=404,
            error_type="ExecutionTaskNotFound",
            message=f"Execution task not found: {task_id}",
            details={"task_id": task_id},
        )
    task = _execution_task_info(cancellation.snapshot)
    return ExecutionTaskCancelResponse(
        task=task,
        cancelled=cancellation.effective,
    )


async def get_active_chat_task(session_id: str) -> ExecutionTaskInfo:
    """Return the active task for a chat session."""
    runtime = get_runtime_context()
    snapshots = await runtime.task_coordinator.list_tasks(
        scope=chat_session_scope(session_id),
        include_terminal=False,
    )
    if not snapshots:
        raise APIException(
            status_code=404,
            error_type="ExecutionTaskNotFound",
            message=f"No active execution task for chat session: {session_id}",
            details={"session_id": session_id},
        )
    return _execution_task_info(snapshots[-1])


async def cancel_chat_session_task(session_id: str) -> ExecutionTaskCancelResponse:
    """Request cancellation for the active task in a chat session."""
    task = await get_active_chat_task(session_id)
    return await cancel_execution_task(task.task_id)


async def list_workflow_tasks(vault_name: str | None = None) -> ExecutionTaskListResponse:
    """List process-local workflow task snapshots."""
    scope = workflow_vault_scope(vault_name) if vault_name else None
    return await list_execution_tasks(kind=ExecutionTaskKind.WORKFLOW.value, scope=scope)


def get_vault_task_mutations(
    *,
    vault_name: str,
    limit: int = 50,
    task_id: str | None = None,
    include_expired: bool = False,
    operation: str | None = None,
) -> VaultTaskMutationsResponse:
    """Return durable file mutation activity for one vault."""
    _get_vault_path(vault_name)
    groups = VaultStateService().list_task_mutations(
        vault_name=vault_name,
        limit=limit,
        task_id=task_id,
        include_expired=include_expired,
        operation=operation,
    )
    return VaultTaskMutationsResponse(
        vault_name=vault_name,
        groups=[
            _vault_task_mutation_group_info(group)
            for group in groups
        ],
    )


def cleanup_vault_state() -> VaultStateCleanupResponse:
    """Manually delete expired vault-state safety artifacts."""
    result = cleanup_expired_vault_state()
    return VaultStateCleanupResponse(
        success=True,
        expired_mutation_rows_deleted=result.expired_mutation_rows_deleted,
        expired_snapshot_rows_deleted=result.expired_snapshot_rows_deleted,
        snapshot_files_deleted=result.snapshot_files_deleted,
        snapshot_dirs_deleted=result.snapshot_dirs_deleted,
        message=(
            "Vault-state cleanup completed: "
            f"{result.expired_mutation_rows_deleted} mutation row(s), "
            f"{result.expired_snapshot_rows_deleted} snapshot row(s), "
            f"{result.snapshot_files_deleted} snapshot file(s), "
            f"{result.snapshot_dirs_deleted} snapshot directory/directories deleted."
        ),
    )


def get_vault_snapshot_file(snapshot_id: int) -> SnapshotFileResponse:
    """Resolve a retained vault snapshot file for inline display."""
    if snapshot_id <= 0:
        raise APIException(
            status_code=400,
            error_type="InvalidSnapshotId",
            message="Snapshot id must be a positive integer.",
            details={"snapshot_id": snapshot_id},
        )

    snapshot = VaultStateService().resolve_snapshot_file(snapshot_id)
    if snapshot is None:
        raise APIException(
            status_code=404,
            error_type="VaultSnapshotNotFound",
            message=f"Vault snapshot not found or no longer retained: {snapshot_id}",
            details={"snapshot_id": snapshot_id},
        )

    return SnapshotFileResponse(
        path=snapshot.path,
        filename=Path(snapshot.vault_path).name or f"snapshot-{snapshot_id}",
        media_type=mimetypes.guess_type(snapshot.vault_path)[0] or "text/plain",
    )


def _vault_task_mutation_group_info(group) -> VaultTaskMutationGroupInfo:
    chat_session = None
    if group.activity_kind == "chat" and group.chat_session_id:
        chat_session = _chat_store.get_session(group.chat_session_id, group.vault_name)
    return VaultTaskMutationGroupInfo(
        activity_id=group.activity_id,
        activity_kind=group.activity_kind,
        activity_label=group.activity_label,
        chat_session_id=group.chat_session_id,
        chat_session_title=chat_session.title if chat_session else group.chat_session_title,
        chat_session_created_at=chat_session.created_at if chat_session else group.chat_session_created_at,
        chat_session_last_activity_at=(
            chat_session.last_activity_at if chat_session else group.chat_session_last_activity_at
        ),
        task_id=group.task_id,
        task_kind=group.task_kind,
        task_source=group.task_source,
        task_scope=group.task_scope,
        task_label=group.task_label,
        vault_id=group.vault_id,
        vault_name=group.vault_name,
        mutation_count=group.mutation_count,
        first_mutation_at=group.first_mutation_at,
        last_mutation_at=group.last_mutation_at,
        expires_at=group.expires_at,
        mutations=[
            VaultTaskMutationInfo(
                id=mutation.id,
                task_id=mutation.task_id,
                task_kind=mutation.task_kind,
                task_source=mutation.task_source,
                task_scope=mutation.task_scope,
                task_label=mutation.task_label,
                path=mutation.path,
                related_path=mutation.related_path,
                operation=mutation.operation,
                event_sequence=mutation.event_sequence,
                before_exists=mutation.before_exists,
                before_hash=mutation.before_hash,
                before_snapshot_id=mutation.before_snapshot_id,
                after_exists=mutation.after_exists,
                after_hash=mutation.after_hash,
                after_snapshot_id=mutation.after_snapshot_id,
                snapshot_ref=mutation.snapshot_ref,
                created_at=mutation.created_at,
                expires_at=mutation.expires_at,
            )
            for mutation in group.mutations
        ],
    )


def purge_expired_cache() -> CachePurgeResponse:
    """Delete expired cache artifacts on demand."""
    now = datetime.now()
    purged_count = purge_expired_cache_artifacts(now=now)
    logger.info(
        "Manual cache purge completed",
        data={
            "purged_count": purged_count,
            "now": now.isoformat(),
        },
    )
    return CachePurgeResponse(
        success=True,
        message=f"Purged {purged_count} expired cache artifact(s).",
        purged_count=purged_count,
    )


def get_system_database_migration_status() -> SystemMigrationStatusResponse:
    """Return registered system database migration status."""
    try:
        status = get_registered_system_migration_status(get_system_root())
    except Exception as exc:
        raise SystemConfigurationError(f"Failed to inspect system database migrations: {exc}") from exc

    return _build_system_migration_status_response(status)


def run_system_database_migrations(backup: bool = True) -> SystemMigrationRunResponse:
    """Run registered system database migrations on demand."""
    try:
        status = run_registered_system_migrations(get_system_root(), backup=backup)
    except Exception as exc:
        raise SystemConfigurationError(f"Failed to run system database migrations: {exc}") from exc

    backups_created = [
        target.backup_path
        for target in status.targets
        if target.backup_path
    ]
    message = (
        "System database migrations completed."
        if status.pending_count == 0
        else f"System database migrations completed with {status.pending_count} migration(s) still pending."
    )
    logger.info(
        "Manual system database migration run completed",
        data={
            "pending_count": status.pending_count,
            "backups_created": len(backups_created),
            "backup": backup,
        },
    )
    response = _build_system_migration_status_response(status, message=message)
    return SystemMigrationRunResponse(
        **response.model_dump(),
        backups_created=backups_created,
    )


def _build_system_migration_status_response(
    status,
    *,
    message: str | None = None,
) -> SystemMigrationStatusResponse:
    pending_count = status.pending_count
    summary = message or (
        "All registered system database migrations are applied."
        if pending_count == 0
        else f"{pending_count} system database migration(s) pending."
    )
    return SystemMigrationStatusResponse(
        success=True,
        message=summary,
        system_root=status.system_root,
        pending_count=pending_count,
        targets=[
            SystemMigrationTargetInfo(
                db_name=target.db_name,
                namespace=target.namespace,
                db_path=target.db_path,
                exists=target.exists,
                applied_versions=list(target.applied_versions),
                pending_versions=list(target.pending_versions),
                backup_path=target.backup_path,
            )
            for target in status.targets
        ],
    )


def refresh_system_authoring_templates() -> SystemTemplateSeedResponse:
    """Refresh packaged system Authoring templates on demand."""
    try:
        result = seed_system_templates(get_system_root(), overwrite=True)
    except Exception as exc:
        raise SystemConfigurationError(f"Failed to refresh system authoring templates: {exc}") from exc

    created = result.get("created", [])
    updated = result.get("updated", [])
    skipped = result.get("skipped", [])
    errors = result.get("errors", [])
    success = bool(result.get("success", False))

    logger.info(
        "Manual system authoring template refresh completed",
        data={
            "created": len(created),
            "updated": len(updated),
            "skipped": len(skipped),
            "errors": len(errors),
            "success": success,
        },
    )

    message = (
        "System authoring templates refreshed: "
        f"{len(created)} created, {len(updated)} updated, {len(skipped)} skipped."
    )
    if errors:
        message += f" {len(errors)} error(s) occurred."

    return SystemTemplateSeedResponse(
        success=success,
        message=message,
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


def get_workflow_load_errors(
    *,
    vault_name: str | None = None,
    workflow_name: str | None = None,
) -> List[APIConfigurationError]:
    """Return workflow configuration errors, optionally filtered by vault/workflow."""
    errors = get_configuration_errors()
    if vault_name:
        errors = [error for error in errors if error.vault == vault_name]
    if workflow_name:
        errors = [error for error in errors if error.workflow_name == workflow_name]
    return errors


def _get_workflow_loader():
    """Get workflow loader from runtime context."""
    runtime = get_runtime_context()
    return runtime.workflow_loader


def _get_vault_path(vault_name: str) -> str:
    """Return vault path from loader cache."""
    vault_info = _get_workflow_loader().get_vault_info()
    if vault_name not in vault_info:
        raise ValueError(f"Vault '{vault_name}' not found")
    return vault_info[vault_name].get("path")


def set_system_startup_time(startup_time: datetime):
    """Set the system startup time for status reporting."""
    global _system_startup_time
    _system_startup_time = startup_time


def list_context_templates(vault_name: str) -> List[TemplateInfo]:
    """List available context templates for a given vault."""
    vault_path: Optional[str] = None
    try:
        vault_path = _get_vault_path(vault_name)
    except Exception as exc:
        logger.warning(f"Vault path lookup failed for '{vault_name}', falling back to system templates only: {exc}")

    templates = list_templates(Path(vault_path) if vault_path else None)
    results: List[TemplateInfo] = []
    for tmpl in templates:
        results.append(
            TemplateInfo(
                name=tmpl.name,
                source=tmpl.source,
                path=str(tmpl.path) if tmpl.path else None,
            )
        )
    return results


def list_chat_sessions(vault_name: str) -> List[ChatSessionInfo]:
    """List persisted chat sessions for a vault ordered by latest activity."""
    sessions = _chat_store.list_sessions(vault_name)
    summary_store = SessionSummaryStore()
    return [
        ChatSessionInfo(
            session_id=session.session_id,
            created_at=session.created_at,
            last_activity_at=session.last_activity_at,
            title=session.title or None,
            workspace=_chat_workspace_info(
                _chat_store.get_session_workspace_path(session.session_id, vault_name)
            ),
            has_summary=summary_store.get_session_summary(
                vault_name=vault_name,
                session_id=session.session_id,
            )
            is not None,
        )
        for session in sessions
    ]


def fork_chat_session(
    *,
    vault_name: str,
    source_session_id: str,
    through_sequence_index: int,
) -> ChatSessionForkResponse:
    """Create a new chat session from a source session prefix."""
    source_session = _chat_store.get_session_by_id(source_session_id)
    if source_session is None:
        raise APIException(
            status_code=404,
            error_type="ChatSessionNotFound",
            message=f"Chat session not found: {source_session_id}",
            details={"session_id": source_session_id, "vault_name": vault_name},
        )
    if source_session.vault_name != vault_name:
        raise APIException(
            status_code=409,
            error_type="ChatSessionVaultMismatch",
            message=(
                f"Chat session '{source_session_id}' belongs to vault "
                f"'{source_session.vault_name}' and cannot be used with vault '{vault_name}'."
            ),
            details={
                "session_id": source_session_id,
                "requested_vault": vault_name,
                "bound_vault": source_session.vault_name,
            },
        )

    highest_sequence = _chat_store.get_highest_message_sequence_index(source_session_id, vault_name)
    if highest_sequence < 0:
        raise APIException(
            status_code=400,
            error_type="ChatSessionForkEmpty",
            message=f"Chat session has no messages to fork: {source_session_id}",
            details={"session_id": source_session_id, "vault_name": vault_name},
        )
    if through_sequence_index > highest_sequence:
        raise APIException(
            status_code=400,
            error_type="ChatSessionForkPointInvalid",
            message=(
                f"Fork point {through_sequence_index} is beyond the latest "
                f"message sequence {highest_sequence}."
            ),
            details={
                "session_id": source_session_id,
                "vault_name": vault_name,
                "through_sequence_index": through_sequence_index,
                "highest_sequence_index": highest_sequence,
            },
        )

    new_session_id = _generate_unique_chat_session_id(vault_name)
    new_title = _forked_session_title(source_session)
    copied_message_count = _chat_store.fork_session(
        source_session_id=source_session_id,
        new_session_id=new_session_id,
        vault_name=vault_name,
        through_sequence_index=through_sequence_index,
        title=new_title,
        metadata_update={
            "fork": {
                "source_session_id": source_session_id,
                "through_sequence_index": through_sequence_index,
                "created_at": datetime.now(UTC).isoformat(),
            }
        },
    )
    new_session = _chat_store.get_session(session_id=new_session_id, vault_name=vault_name)
    if new_session is None:  # pragma: no cover - defensive consistency check
        raise RuntimeError(f"Forked session was not persisted: {new_session_id}")

    logger.info(
        "Chat session forked",
        data={
            "vault_name": vault_name,
            "source_session_id": source_session_id,
            "new_session_id": new_session_id,
            "through_sequence_index": through_sequence_index,
            "copied_message_count": copied_message_count,
            "workspace_path": _chat_store.get_session_workspace_path(new_session_id, vault_name) or None,
        },
    )
    return ChatSessionForkResponse(
        session=ChatSessionInfo(
            session_id=new_session.session_id,
            created_at=new_session.created_at,
            last_activity_at=new_session.last_activity_at,
            title=new_session.title or None,
            workspace=_chat_workspace_info(
                _chat_store.get_session_workspace_path(new_session.session_id, vault_name)
            ),
            has_summary=False,
        ),
        source_session_id=source_session_id,
        through_sequence_index=through_sequence_index,
        copied_message_count=copied_message_count,
    )


def _generate_unique_chat_session_id(vault_name: str) -> str:
    base_session_id = generate_session_id(vault_name)
    generated_session_id = base_session_id
    suffix = 1
    while _chat_store.get_session_by_id(generated_session_id) is not None:
        suffix += 1
        generated_session_id = f"{base_session_id}_{suffix}"
    return generated_session_id


def _forked_session_title(source_session: StoredChatSession) -> str:
    title = (source_session.title or "").strip()
    if title:
        return f"{title} (fork)"
    return f"Fork of {source_session.session_id}"


def get_chat_session_summary(vault_name: str, session_id: str) -> dict:
    """Return a lightweight summary preview for one chat session."""
    session_summary = SessionSummaryStore().get_session_summary(
        vault_name=vault_name,
        session_id=session_id,
    )
    if session_summary is None:
        return {
            "session_id": session_id,
            "vault_name": vault_name,
            "has_summary": False,
            "summary": None,
            "user_intent": None,
            "created_at": None,
            "updated_at": None,
            "domain": None,
            "work_product": None,
            "workspace_path": _chat_store.get_session_workspace_path(session_id, vault_name) or None,
            "named_entities": None,
            "source_summary": None,
            "metadata": {},
            "artifacts": [],
            "vector_index": {
                "indexed_fields": 0,
                "expected_fields": 0,
                "indexed_field_types": [],
                "missing_field_types": [],
            },
        }
    return _session_summary_response(session_summary)


async def update_chat_session_summary(
    *,
    vault_name: str,
    session_id: str,
    data: dict[str, Any],
) -> dict:
    """Manually update one session summary record and refresh search indexes."""
    store = SessionSummaryStore()
    existing = store.get_session_summary(vault_name=vault_name, session_id=session_id)
    if existing is None:
        raise APIException(
            status_code=404,
            error_type="SessionSummaryNotFound",
            message=f"Session summary not found: {session_id}",
            details={"session_id": session_id, "vault_name": vault_name},
        )
    previous = existing
    session_summary = store.update_session_summary_fields(
        vault_name=vault_name,
        session_id=session_id,
        summary=data.get("summary"),
        domain=data.get("domain"),
        work_product=data.get("work_product"),
        user_intent=data.get("user_intent"),
        workspace_path=data.get("workspace_path"),
        named_entities=data.get("named_entities"),
        source_summary=data.get("source_summary"),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )
    try:
        indexed_fields = await _index_session_summary_for_api(
            store,
            vault_name=vault_name,
            session_id=session_id,
        )
    except Exception:
        _restore_session_summary_for_api(
            store,
            vault_name=vault_name,
            session_id=session_id,
            previous_summary=previous,
        )
        raise
    response = _session_summary_response(session_summary)
    response["indexed_fields"] = indexed_fields
    return response


def delete_chat_session_summary(vault_name: str, session_id: str) -> dict:
    """Delete one session summary record without deleting the chat session."""
    deleted = SessionSummaryStore().delete_session_summary(
        vault_name=vault_name,
        session_id=session_id,
    )
    return {
        "session_id": session_id,
        "vault_name": vault_name,
        "deleted": deleted,
    }


async def _index_session_summary_for_api(
    store: SessionSummaryStore,
    *,
    vault_name: str,
    session_id: str,
) -> int:
    try:
        indexed_fields = await store.index_session_summary_fields(
            vault_name=vault_name,
            session_id=session_id,
            vector_service=VectorService(),
        )
        logger.info(
            "session_summary_field_indexing_completed",
            data={
                "source": "api",
                "vault_name": vault_name,
                "session_id": session_id,
                "indexed_fields": indexed_fields,
            },
        )
        return indexed_fields
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "session_summary_field_indexing_failed",
            data={
                "source": "api",
                "vault_name": vault_name,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise APIException(
            status_code=500,
            error_type="SessionSummaryIndexingFailed",
            message=f"Failed to refresh session summary vector index for {session_id}",
            details={
                "session_id": session_id,
                "vault_name": vault_name,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        ) from exc


def _restore_session_summary_for_api(
    store: SessionSummaryStore,
    *,
    vault_name: str,
    session_id: str,
    previous_summary,
) -> None:
    store.upsert_session_summary(
        vault_name=vault_name,
        session_id=session_id,
        title=previous_summary.title,
        summary=previous_summary.summary,
        domain=previous_summary.domain,
        work_product=previous_summary.work_product,
        user_intent=previous_summary.user_intent,
        named_entities=previous_summary.named_entities,
        source_summary=previous_summary.source_summary,
        workspace_path=previous_summary.workspace_path,
        metadata=previous_summary.metadata,
    )
    if previous_summary.artifacts:
        store.add_session_artifacts(
            vault_name=vault_name,
            session_id=session_id,
            artifacts=tuple(previous_summary.artifacts),
        )


def _session_summary_response(session_summary) -> dict:
    return {
        "session_id": session_summary.session_id,
        "vault_name": session_summary.vault_name,
        "has_summary": True,
        "summary": session_summary.summary,
        "user_intent": session_summary.user_intent,
        "created_at": session_summary.created_at,
        "updated_at": session_summary.updated_at,
        "domain": session_summary.domain,
        "work_product": session_summary.work_product,
        "workspace_path": session_summary.workspace_path,
        "named_entities": session_summary.named_entities,
        "source_summary": session_summary.source_summary,
        "metadata": session_summary.metadata,
        "artifacts": [artifact.to_dict() for artifact in session_summary.artifacts],
        "vector_index": SessionSummaryStore().get_session_summary_vector_index_status(
            vault_name=session_summary.vault_name,
            session_id=session_summary.session_id,
        ),
    }


def get_chat_session_detail(vault_name: str, session_id: str) -> ChatSessionDetailResponse:
    """Return persisted chat messages for one session."""
    messages = _chat_store.get_stored_messages(session_id, vault_name)
    tool_events = _chat_store.get_tool_events(session_id, vault_name, committed_only=True)
    metadata = _chat_store.get_session_metadata(session_id, vault_name)
    latest_failure = _chat_session_failure_info(metadata.get("latest_turn_failure"))
    return ChatSessionDetailResponse(
        session_id=session_id,
        vault_name=vault_name,
        workspace=_chat_workspace_info(_chat_store.get_session_workspace_path(session_id, vault_name)),
        latest_failure=latest_failure,
        messages=[
            ChatSessionMessageInfo(
                sequence_index=message.sequence_index,
                role=message.role,
                content=message.content_text,
                message_type=message.message_type,
                direction=message.direction,
                is_tool_message=(
                    _is_tool_message_text(message.content_text)
                    or bool(message.tool_call_ids)
                    or bool(message.tool_return_ids)
                ),
                tool_call_ids=list(message.tool_call_ids),
                tool_return_ids=list(message.tool_return_ids),
            )
            for message in messages
        ],
        tool_events=[
            ChatSessionToolEventInfo(
                tool_call_id=event.tool_call_id,
                tool_name=event.tool_name,
                event_type=event.event_type,
                created_at=event.created_at,
                args=_load_json_object(event.args_json),
                result_text=event.result_text,
                result_metadata=_load_json_object(event.result_metadata_json) or {},
                artifact_ref=event.artifact_ref,
            )
            for event in tool_events
        ],
    )


def _chat_session_failure_info(value: Any) -> ChatSessionFailureInfo | None:
    if not isinstance(value, dict):
        return None
    if value.get("status") != "failed":
        return None
    try:
        return ChatSessionFailureInfo(
            status=str(value.get("status") or "failed"),
            phase=str(value.get("phase") or "unknown"),
            streaming=bool(value.get("streaming")),
            error_type=str(value.get("error_type") or "Error"),
            error=str(value.get("error") or ""),
            model=None if value.get("model") is None else str(value.get("model")),
            tools=[str(item) for item in value.get("tools") or ()],
            accepted_user_sequence_index=int(value.get("accepted_user_sequence_index")),
            recorded_at=str(value.get("recorded_at") or ""),
            suggested_action=str(value.get("suggested_action") or ""),
        )
    except (TypeError, ValueError):
        return None


def set_chat_session_title(vault_name: str, session_id: str, title: str | None) -> None:
    """Set or clear the user-defined title for a chat session."""
    _chat_store.set_session_title(session_id, vault_name, title)


def export_chat_session_markdown(vault_name: str, vault_path: str, session_id: str) -> ChatSessionExportResponse:
    """Export one chat session transcript to the vault on demand."""
    session_summary = SessionSummaryStore().get_session_summary(
        vault_name=vault_name,
        session_id=session_id,
    )
    exported = export_chat_transcript(
        store=_chat_store,
        vault_path=vault_path,
        vault_name=vault_name,
        session_id=session_id,
        session_summary=session_summary.summary if session_summary else None,
    )
    return ChatSessionExportResponse(
        session_id=session_id,
        filename=exported.filename,
        path=exported.path,
    )


async def get_chat_history_compaction_status(
    vault_name: str,
    session_id: str,
) -> ChatHistoryCompactionStatusResponse:
    """Return compaction status for one chat session."""
    status = await get_compaction_status(
        session_id=session_id,
        vault_name=vault_name,
        store=_chat_store,
    )
    return ChatHistoryCompactionStatusResponse(**asdict(status))


async def compact_chat_session_history(
    vault_name: str,
    vault_path: str,
    session_id: str,
    *,
    focus: str | None,
) -> ChatHistoryCompactionResponse:
    """Compact one chat session through the shared compaction service."""
    runtime = get_runtime_context()
    async with runtime.task_coordinator.track_current_task(
        kind=ExecutionTaskKind.HISTORY_COMPACTION,
        scope=chat_session_scope(session_id),
        source=ExecutionTaskSource.API,
        label=compaction_task_label(session_id),
        metadata={"vault": vault_name, "session_id": session_id},
    ):
        result = await compact_chat_history(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
            focus=focus,
            source=ExecutionTaskSource.API,
            store=_chat_store,
        )
    return ChatHistoryCompactionResponse(**result.as_api_dict())


def delete_chat_session(vault_name: str, vault_path: str, session_id: str) -> None:
    """Delete one chat session and its session summary."""
    del vault_path
    _chat_store.delete_sessions(vault_name, session_id=session_id)
    SessionSummaryStore().delete_session_summary(vault_name=vault_name, session_id=session_id)


def purge_chat_sessions(
    vault_name: str,
    vault_path: str,
    *,
    older_than_days: int | None,
) -> ChatSessionsPurgeResponse:
    """Delete old chat sessions and their transcript files for a vault."""
    deleted_ids = _chat_store.delete_sessions(vault_name, older_than_days=older_than_days)
    summary_store = SessionSummaryStore()
    for session_id in deleted_ids:
        summary_store.delete_session_summary(vault_name=vault_name, session_id=session_id)
    remove_chat_transcript_exports(vault_path=vault_path, session_ids=deleted_ids)

    n = len(deleted_ids)
    if n == 0:
        message = "No sessions matched."
    elif n == 1:
        message = "Deleted 1 session."
    else:
        message = f"Deleted {n} sessions."
    return ChatSessionsPurgeResponse(deleted=n, message=message)


def _is_tool_message_text(content: str) -> bool:
    text = (content or "").strip()
    return text.startswith("[") and "]" in text


def _load_json_object(raw_value: str | None) -> Dict[str, Any] | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return {"raw": raw_value}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


async def collect_vault_status() -> List[VaultInfo]:
    """
    Collect status information about all discovered vaults from cached data.

    Returns:
        List of VaultInfo objects with vault details

    Raises:
        SystemConfigurationError: If vault discovery fails
    """
    try:
        # Use cached vault info from workflow loader
        vault_data = _get_workflow_loader().get_vault_info()
        vault_state_summary = _collect_vault_state_summary()

        # Create VaultInfo objects from cached data
        vault_infos = []
        for vault_name, data in vault_data.items():
            state_summary = vault_state_summary.get(vault_name, {})
            vault_info = VaultInfo(
                name=vault_name,
                path=data['path'],
                workflow_count=len(data['workflows']),
                workflows=data['workflows'],
                tracked_files=state_summary.get("tracked_files"),
                files_created_recent=state_summary.get("files_created_recent"),
                files_deleted_recent=state_summary.get("files_deleted_recent"),
                latest_vault_change_at=state_summary.get("latest_vault_change_at"),
            )
            vault_infos.append(vault_info)

        return vault_infos

    except Exception as e:
        error_msg = f"Failed to collect vault status: {str(e)}"
        raise SystemConfigurationError(error_msg) from e


def _collect_vault_state_summary() -> Dict[str, Dict[str, Any]]:
    """Return cheap vault-state summary fields keyed by current vault name."""
    summary: Dict[str, Dict[str, Any]] = {}
    recent_change_cutoff = datetime.now(UTC) - timedelta(days=7)
    try:
        service = VaultStateService()
        with service.SessionFactory() as session:
            file_rows = session.execute(
                select(VaultFile.vault_name, func.count())
                .where(VaultFile.deleted_at.is_(None))
                .group_by(VaultFile.vault_name)
            ).all()
            for vault_name, count in file_rows:
                summary.setdefault(vault_name, {})["tracked_files"] = int(count)

            change_rows = session.execute(
                select(VaultFileEvent.vault_name, func.max(VaultFileEvent.observed_at))
                .group_by(VaultFileEvent.vault_name)
            ).all()
            for vault_name, latest_change in change_rows:
                summary.setdefault(vault_name, {})[
                    "latest_vault_change_at"
                ] = latest_change

            recent_change_rows = session.execute(
                select(VaultFileEvent.vault_name, VaultFileEvent.event_type, func.count())
                .where(
                    VaultFileEvent.observed_at >= recent_change_cutoff,
                    VaultFileEvent.event_type.in_(("created", "deleted")),
                )
                .group_by(VaultFileEvent.vault_name, VaultFileEvent.event_type)
            ).all()
            for vault_name, event_type, count in recent_change_rows:
                key = "files_created_recent" if event_type == "created" else "files_deleted_recent"
                summary.setdefault(vault_name, {})[key] = int(count)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to collect vault-state status summary",
            data={
                "event": "vault_state_status_summary_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
    return summary


def collect_scheduler_status(scheduler=None) -> SchedulerInfo:
    """
    Collect status information about the scheduler using APScheduler methods.

    Args:
        scheduler: APScheduler instance (optional, will try to get from main if None)

    Returns:
        SchedulerInfo object with scheduler details and job information
    """
    try:
        # If no scheduler provided, get from runtime context
        if scheduler is None:
            try:
                runtime = get_runtime_context()
                scheduler = runtime.scheduler
            except RuntimeStateError:
                scheduler = None

        if scheduler is None:
            # Return default scheduler info if unavailable
            return SchedulerInfo(
                running=False,
                total_jobs=0,
                enabled_workflows=0,
                disabled_workflows=0
            )

        # Get scheduler status
        is_running = scheduler.running

        # Get detailed job information using APScheduler's get_jobs()
        jobs = scheduler.get_jobs()
        total_jobs = len(jobs)

        # Extract job details from APScheduler
        job_summaries = []
        for job in jobs:
            history = get_scheduler_job_history(job.id) or {}
            job_summary = {
                'id': job.id,
                'name': job.name,
                'job_type': 'system' if job.id in SYSTEM_JOB_IDS else 'workflow',
                'next_run_time': job.next_run_time,
                'last_run_time': history.get('last_run_time'),
                'last_status': history.get('last_status'),
                'last_error': history.get('last_error'),
                'trigger_type': type(job.trigger).__name__,
                'trigger_description': str(job.trigger),
                'max_instances': job.max_instances,
                'misfire_grace_time': job.misfire_grace_time
            }
            job_summaries.append(job_summary)

        # Sort by next run time for better display
        job_summaries.sort(key=lambda x: x['next_run_time'] or datetime.max)

        # Remove redundant workflow counting - this will be done at the higher level using cached data
        scheduler_info = SchedulerInfo(
            running=is_running,
            total_jobs=total_jobs,
            enabled_workflows=0,  # Will be calculated elsewhere
            disabled_workflows=0,  # Will be calculated elsewhere
            job_details=job_summaries  # Add rich job data
        )

        return scheduler_info

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to collect scheduler status",
            data={
                "event": "scheduler_status_collection_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return SchedulerInfo(
            running=False,
            total_jobs=0,
            enabled_workflows=0,
            disabled_workflows=0,
            job_details=[]
        )


async def scan_import_folder(
    vault: str,
    queue_only: bool = False,
    strategies: list[str] | None = None,
    capture_ocr_images: bool | None = None,
    pdf_mode: str | None = None,
):
    """
    Enqueue ingestion jobs and process inline jobs under execution task context.
    """
    runtime, ingest_service, jobs_created, skipped = _enqueue_import_scan_jobs(
        vault=vault,
        strategies=strategies,
        capture_ocr_images=capture_ocr_images,
        pdf_mode=pdf_mode,
    )

    if not queue_only and jobs_created:
        refreshed_jobs = []
        for job in jobs_created:
            await _process_ingestion_job_for_api(runtime, ingest_service, job.id, vault)
            refreshed_jobs.append(ingest_service.get_job(job.id) or job)
        jobs_created = refreshed_jobs

    logger.info(
        "Import scan completed",
        data={
            "vault": vault,
            "jobs_created": len(jobs_created),
            "skipped": len(skipped),
            "queue_only": queue_only,
        },
    )

    return jobs_created, skipped


def _enqueue_import_scan_jobs(
    *,
    vault: str,
    strategies: list[str] | None,
    capture_ocr_images: bool | None,
    pdf_mode: str | None,
):
    """Create ingestion jobs for supported files in a vault import folder."""
    runtime = get_runtime_context()
    import_root = Path(runtime.config.data_root) / vault / ASSISTANTMD_ROOT_DIR / IMPORT_DIR
    legacy_import_root = Path(runtime.config.data_root) / vault / ASSISTANTMD_ROOT_DIR / "import"
    import_root.mkdir(parents=True, exist_ok=True)

    ingest_service: IngestionService = runtime.ingestion

    jobs_created = []
    skipped = []
    supported_exts = {key for key in importer_registry.keys() if key.startswith(".")}

    search_roots = [import_root]
    if legacy_import_root.exists():
        search_roots.append(legacy_import_root)

    extractor_options: dict[str, Any] = {}
    if capture_ocr_images is not None:
        extractor_options["ocr_capture_images"] = bool(capture_ocr_images)
    normalized_pdf_mode = (pdf_mode or "").strip().lower()
    if normalized_pdf_mode not in {"", "markdown", "page_images"}:
        normalized_pdf_mode = ""

    for root in search_roots:
        for item in sorted(root.iterdir()):
            if item.is_dir():
                continue
            suffix = item.suffix.lower()
            if suffix not in supported_exts:
                skipped.append(str(item.name))
                continue
            existing_job = find_job_for_source(
                source_uri=item.name,
                vault=vault,
                statuses=[
                    JobStatus.QUEUED.value,
                    JobStatus.PROCESSING.value,
                ],
            )
            if existing_job:
                skipped.append(str(item.name))
                continue

            job_options: dict[str, Any] = {}
            if strategies:
                job_options["strategies"] = strategies
            if extractor_options:
                job_options["extractor_options"] = extractor_options
            if normalized_pdf_mode:
                job_options["pdf_mode"] = normalized_pdf_mode

            job = ingest_service.enqueue_job(
                source_uri=item.name,
                vault=vault,
                source_type=SourceKind.FILE.value,
                mime_hint=None,
                options=job_options,
            )
            jobs_created.append(job)

    return runtime, ingest_service, jobs_created, skipped


async def import_url_direct(vault: str, url: str, clean_html: bool = True):
    """
    Import a single URL immediately with vault mutations grouped as API ingestion.
    """
    runtime = get_runtime_context()
    ingest_service: IngestionService = runtime.ingestion

    job = ingest_service.enqueue_job(
        source_uri=url,
        vault=vault,
        source_type=SourceKind.URL.value,
        mime_hint="text/html",
        options={"extractor_options": {"clean_html": clean_html}},
    )
    await _process_ingestion_job_for_api(runtime, ingest_service, job.id, vault)
    job = ingest_service.get_job(job.id)
    outputs = job.outputs if job else None
    logger.info(
        "Import URL completed",
        data={
            "vault": vault,
            "status": job.status if job else None,
            "outputs_count": len(outputs) if outputs is not None else 0,
            "clean_html": clean_html,
        },
    )
    return job


async def _process_ingestion_job_for_api(
    runtime,
    ingest_service: IngestionService,
    job_id: int,
    vault: str,
) -> None:
    """Process one API-triggered ingestion job under execution task context."""
    try:
        await process_ingestion_job_in_task(
            task_coordinator=runtime.task_coordinator,
            process_job_fn=ingest_service.process_job,
            job_id=job_id,
            vault=vault,
            source=ExecutionTaskSource.API,
        )
    except Exception:
        # process_job updates status/error; callers inspect refreshed job state.
        pass


def collect_system_health() -> SystemInfo:
    """
    Collect system health information.
    
    Returns:
        SystemInfo object with system health details
    """
    try:
        # Get startup time
        startup_time = _system_startup_time or datetime.now()
        
        runtime = get_runtime_context()
        workflow_loader = runtime.workflow_loader

        # Prefer explicit runtime timestamp, fall back to loader metadata.
        last_reload = runtime.last_config_reload
        if last_reload is None and hasattr(workflow_loader, "_last_loaded"):
            last_reload = workflow_loader._last_loaded

        # Get data root
        data_root = workflow_loader._data_root
        
        system_info = SystemInfo(
            startup_time=startup_time,
            last_config_reload=last_reload,
            data_root=data_root
        )
        
        
        return system_info
        
    except Exception:
        # Return safe defaults on error
        return SystemInfo(
            startup_time=datetime.now(),
            data_root="/app/data"
        )


async def get_system_status(scheduler=None) -> StatusResponse:
    """
    Collect comprehensive system status information from cached data.

    Args:
        scheduler: APScheduler instance (optional)

    Returns:
        StatusResponse with complete system status

    Raises:
        SystemConfigurationError: If critical status collection fails
    """
    try:
        # Use cached data - no reloading
        # Collect vault information
        vaults = await collect_vault_status()

        # Collect scheduler status
        scheduler_info = collect_scheduler_status(scheduler)

        # Collect system health
        system_info = collect_system_health()

        total_vaults = len(vaults)
        total_workflows = sum(vault.workflow_count for vault in vaults)

        workflow_summaries = get_workflow_summaries()
        enabled_workflows = [summary for summary in workflow_summaries if summary.enabled]
        disabled_workflows = [summary for summary in workflow_summaries if not summary.enabled]
        system_workflow_templates = get_system_workflow_template_summaries()

        scheduler_info.enabled_workflows = len(enabled_workflows)
        scheduler_info.disabled_workflows = len(disabled_workflows)

        # Get configuration errors and overall configuration health
        configuration_errors = get_configuration_errors()
        configuration_status_snapshot = validate_settings()
        default_model_value = None
        try:
            default_entry = get_general_settings().get("default_model")
            if default_entry and getattr(default_entry, "value", None):
                default_model_value = str(default_entry.value).strip() or None
        except Exception:
            default_model_value = None

        configuration_status = ConfigurationStatusInfo(
            issues=[
                ConfigurationIssueInfo(
                    name=issue.name,
                    message=issue.message,
                    severity=issue.severity,
                )
                for issue in configuration_status_snapshot.issues
            ],
            tool_availability=dict(configuration_status_snapshot.tool_availability),
            model_availability=dict(configuration_status_snapshot.model_availability),
            default_model=default_model_value,
        )

        status_response = StatusResponse(
            vaults=vaults,
            scheduler=scheduler_info,
            system=system_info,
            total_vaults=total_vaults,
            total_workflows=total_workflows,
            enabled_workflows=enabled_workflows,
            disabled_workflows=disabled_workflows,
            system_workflow_templates=system_workflow_templates,
            configuration_errors=configuration_errors,
            configuration_status=configuration_status,
        )

        return status_response

    except Exception as e:
        error_msg = f"Failed to collect system status: {str(e)}"
        raise SystemConfigurationError(error_msg) from e


def get_workflow_summaries() -> List[WorkflowSummary]:
    """
    Get summary information about all loaded workflows.

    Returns:
        List of WorkflowSummary objects
    """
    summaries = []

    workflow_loader = _get_workflow_loader()
    all_workflows = getattr(workflow_loader, '_workflows', [])

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
            description=workflow.description
        )
        summaries.append(summary)

    return summaries


def get_system_workflow_template_summaries() -> List[SystemWorkflowTemplateSummary]:
    """Return packaged system workflow templates available to copy into a vault."""
    summaries = []

    for template in list_system_workflow_templates():
        frontmatter = template.frontmatter
        summaries.append(
            SystemWorkflowTemplateSummary(
                name=template.name[:-3] if template.name.endswith(".md") else template.name,
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
        raise ValueError("Workflow file changed since it was opened. Refresh and retry.")

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
        raise ValueError(f"Invalid global_id format. Expected 'vault/name' or 'system/name', got: {global_id}")

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
            if (record.name[:-3] if record.name.endswith(".md") else record.name) == template_name
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
        raise ValueError("System workflow editing only supports markdown authoring files")
    if not template_path.is_file():
        raise ValueError(f"System workflow template file not found: {global_id}")
    return template_path


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def set_workflow_enabled_state(global_id: str, enabled: bool) -> WorkflowEnabledResponse:
    """Set one workflow or system workflow template enabled flag."""
    normalized_id = str(global_id or "").strip()
    if "/" not in normalized_id:
        raise ValueError(f"Invalid global_id format. Expected 'vault/name' or 'system/name', got: {global_id}")

    if normalized_id.startswith("system/"):
        return await _set_system_workflow_enabled_state(normalized_id, enabled)

    vault_name, workflow_name = normalized_id.split("/", 1)
    if not vault_name or not workflow_name:
        raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")

    operation = "enable_workflow" if enabled else "disable_workflow"
    result = await WorkflowRun._set_workflow_enabled_state(
        operation=operation,
        vault_name=vault_name,
        workflow_name=workflow_name,
    )
    if not result.get("success"):
        raise ValueError(str(result.get("message") or f"Workflow not found: {normalized_id}"))

    return WorkflowEnabledResponse(
        success=True,
        global_id=normalized_id,
        enabled_before=bool(result.get("enabled_before", False)),
        enabled_after=bool(result.get("enabled_after", enabled)),
        message=str(result.get("message") or f"Workflow '{normalized_id}' updated."),
    )


async def _set_system_workflow_enabled_state(global_id: str, enabled: bool) -> WorkflowEnabledResponse:
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


def get_configuration_errors() -> List[APIConfigurationError]:
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
            timestamp=error.timestamp
        )
        api_errors.append(api_error)
    
    return api_errors


async def rescan_vaults_and_update_scheduler(scheduler=None) -> Dict[str, Any]:
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


async def get_system_activity_log(limit_bytes: int = 65_536) -> SystemLogResponse:
    """
    Read the system activity log with optional truncation.

    Args:
        limit_bytes: Maximum number of bytes to include from the end of the log.

    Returns:
        SystemLogResponse with the log contents.
    """
    log_path = get_system_root() / "activity.log"

    if limit_bytes is None or limit_bytes <= 0:
        limit_bytes = 65_536

    max_response_bytes = 262_144
    limit_bytes = min(limit_bytes, max_response_bytes)

    if not log_path.exists():
        return SystemLogResponse(
            content="No activity log found yet. Interact with the system to generate entries.",
            truncated=False,
            path=str(log_path),
            size_bytes=0,
            shown_bytes=0
        )

    try:
        raw_bytes = log_path.read_bytes()
    except Exception as exc:
        raise SystemConfigurationError(f"Failed to read activity log: {exc}") from exc

    size_bytes = len(raw_bytes)
    truncated = False

    if size_bytes > limit_bytes:
        truncated = True
        raw_bytes = raw_bytes[-limit_bytes:]

    content = raw_bytes.decode("utf-8", errors="replace")
    shown_bytes = len(raw_bytes)

    return SystemLogResponse(
        content=content,
        truncated=truncated,
        path=str(log_path),
        size_bytes=size_bytes,
        shown_bytes=shown_bytes
    )


def _build_settings_response(path: Path) -> SystemSettingsResponse:
    content = path.read_text(encoding="utf-8")
    return SystemSettingsResponse(
        path=str(path),
        content=content,
        size_bytes=len(content.encode("utf-8"))
    )


async def get_system_settings() -> SystemSettingsResponse:
    """Return the current settings YAML content."""
    path = get_active_settings_path()
    return _build_settings_response(path)


async def update_system_settings(new_content: str) -> SystemSettingsResponse:
    """Validate and persist updated settings YAML content."""
    path = get_active_settings_path()

    try:
        parsed = yaml.safe_load(new_content) if new_content.strip() else {}
    except yaml.YAMLError as exc:
        raise SystemConfigurationError(f"Invalid settings YAML: {exc}") from exc

    if parsed is None:
        parsed = {}

    if not isinstance(parsed, dict):
        raise SystemConfigurationError("Settings YAML must contain a top-level mapping (dictionary).")

    normalized_content = new_content if new_content.endswith('\n') else new_content + '\n'

    try:
        path.write_text(normalized_content, encoding="utf-8")
    except Exception as exc:
        raise SystemConfigurationError(f"Failed to write settings file: {exc}") from exc

    reload_configuration()
    logger.info(
        "Settings updated",
        data={"settings_path": str(path), "content_size": len(normalized_content)},
    )

    return _build_settings_response(path)


def repair_settings_from_template() -> SystemSettingsResponse:
    """
    Merge missing keys from settings.template.yaml into the active settings file.

    - Creates a .bak backup of system/settings.yaml before writing.
    - Adds missing keys; existing values are preserved.
    - Prunes removed settings and removed non-user-editable models/providers/tools.
    """
    # Ensure bootstrap roots exist for path resolution
    set_bootstrap_roots(resolve_bootstrap_data_root(), resolve_bootstrap_system_root())
    active_path = get_active_settings_path()
    backup_path = active_path.with_suffix(".bak")

    try:
        template_raw = yaml.safe_load(SETTINGS_TEMPLATE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise SystemConfigurationError("Template settings file not found.")
    except yaml.YAMLError as exc:
        raise SystemConfigurationError(f"Failed to read template settings: {exc}") from exc

    try:
        active_raw = yaml.safe_load(active_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SystemConfigurationError(f"Failed to read active settings: {exc}") from exc

    if not isinstance(active_raw, dict):
        raise SystemConfigurationError("Active settings file is not a valid mapping.")
    if not isinstance(template_raw, dict):
        raise SystemConfigurationError("Template settings file is not a valid mapping.")

    # Seed merged copy and ensure sections exist
    merged = dict(active_raw)
    for section in ("settings", "models", "providers", "tools"):
        if merged.get(section) is None or not isinstance(merged.get(section), dict):
            merged[section] = {}

    template_sections: Dict[str, dict] = {}
    for section in ("settings", "models", "providers", "tools"):
        section_val = template_raw.get(section)
        template_sections[section] = section_val if isinstance(section_val, dict) else {}

    # Add missing keys from template (non-destructive)
    for section, template_section in template_raw.items():
        if not isinstance(template_section, dict):
            continue
        active_section = merged.get(section)
        if active_section is None or not isinstance(active_section, dict):
            active_section = {}
        for key, value in template_section.items():
            if key not in active_section:
                active_section[key] = value
        merged[section] = active_section

    # Existing core provider entries may need newly introduced non-secret fields
    # from the template. Preserve all active values and only fill absent keys.
    active_providers = merged.get("providers", {})
    template_providers = template_sections.get("providers", {})
    if isinstance(active_providers, dict) and isinstance(template_providers, dict):
        for key, template_provider in template_providers.items():
            active_provider = active_providers.get(key)
            if isinstance(active_provider, dict) and isinstance(template_provider, dict):
                for provider_key, provider_value in template_provider.items():
                    active_provider.setdefault(provider_key, provider_value)

    # Prune removed settings (settings are not user-extensible)
    settings_template_keys = set(template_sections["settings"].keys())
    merged["settings"] = {
        key: val for key, val in merged["settings"].items() if key in settings_template_keys
    }

    def _is_user_editable(entry: Any, default: bool) -> bool:
        if isinstance(entry, dict):
            ue = entry.get("user_editable")
            if isinstance(ue, bool):
                return ue
        return default

    # Prune removed non-editable tools, models, providers while keeping user-editable/custom entries
    def _prune_section(section_name: str, default_user_editable: bool):
        template_section = template_sections.get(section_name, {})
        active_section = merged.get(section_name, {})
        if not isinstance(active_section, dict):
            merged[section_name] = {}
            return

        for key in list(active_section.keys()):
            if key in template_section:
                continue
            entry = active_section.get(key)
            if _is_user_editable(entry, default_user_editable):
                continue
            active_section.pop(key, None)

        merged[section_name] = active_section

    _prune_section("tools", default_user_editable=False)
    _prune_section("models", default_user_editable=True)
    _prune_section("providers", default_user_editable=False)

    try:
        shutil.copyfile(active_path, backup_path)
    except Exception as exc:
        raise SystemConfigurationError(f"Failed to create settings backup: {exc}") from exc

    try:
        active_path.write_text(
            yaml.safe_dump(merged, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
    except Exception as exc:
        raise SystemConfigurationError(f"Failed to write repaired settings: {exc}") from exc

    reload_configuration()
    return _build_settings_response(active_path)


#######################################################################
## Configuration Editing Helpers
#######################################################################


def _format_setting_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, separators=(",", ":"))
        except TypeError:
            return str(value)
    return str(value)


def _build_setting_info(key: str, entry) -> SettingInfo:
    return SettingInfo(
        key=key,
        value=_format_setting_value(getattr(entry, "value", None)),
        description=getattr(entry, "description", None),
        restart_required=bool(getattr(entry, "restart_required", False)),
    )


def get_general_settings_config() -> List[SettingInfo]:
    """Return serialized general settings metadata."""
    settings_map = list_general_settings()
    return [
        _build_setting_info(key, entry)
        for key, entry in settings_map.items()
    ]


def update_general_setting_value(setting_name: str, payload: SettingUpdateRequest) -> SettingInfo:
    """Persist a general setting update and refresh configuration caches."""
    try:
        updated = update_general_setting(setting_name, payload.value)
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration(restart_required=updated.restart_required)
    setting_info = _build_setting_info(setting_name, updated)
    setting_info.restart_required = setting_info.restart_required or reload_result.restart_required
    logger.info(
        "General setting updated",
        data={
            "setting_key": setting_name,
            "restart_required": setting_info.restart_required,
        },
    )
    return setting_info


def _build_model_info(
    name: str,
    config,
    availability: Dict[str, bool],
    issue_messages: Optional[Dict[str, str]] = None,
) -> ModelInfo:
    if hasattr(config, "provider"):
        provider = config.provider
        model_string = config.model_string
        capabilities = list(getattr(config, "capabilities", ["text"]) or ["text"])
        dimensions = getattr(config, "dimensions", None)
        user_editable = getattr(config, "user_editable", True)
        description = getattr(config, "description", None)
    else:
        provider = config['provider']
        model_string = config['model_string']
        capabilities = list(config.get("capabilities", ["text"]) or ["text"])
        dimensions = config.get("dimensions")
        user_editable = config.get('user_editable', True)
        description = config.get('description')

    status_message = None
    if issue_messages:
        status_message = issue_messages.get(name)

    return ModelInfo(
        name=name,
        provider=provider,
        model_string=model_string,
        capabilities=capabilities,
        dimensions=dimensions,
        available=availability.get(name, True),
        user_editable=user_editable,
        description=description,
        status_message=status_message,
    )


def _build_provider_info(name: str, config, restart_required: bool = False) -> ProviderInfo:
    if hasattr(config, "api_key"):
        raw_api_key = config.api_key
        raw_base_url = getattr(config, "base_url", None)
        user_editable = getattr(config, "user_editable", False)
    else:
        raw_api_key = config.get('api_key')
        raw_base_url = config.get('base_url')
        user_editable = config.get('user_editable', False)

    api_key_env = raw_api_key if raw_api_key else None
    base_url_env = raw_base_url if raw_base_url else None

    api_key_has_value = secret_has_value(api_key_env) if api_key_env else False

    if base_url_env and "://" not in base_url_env:
        base_url_has_value = secret_has_value(base_url_env)
    else:
        base_url_has_value = bool(base_url_env)

    return ProviderInfo(
        name=name,
        api_key=api_key_env,
        base_url=base_url_env,
        user_editable=user_editable,
        api_key_has_value=api_key_has_value,
        base_url_has_value=base_url_has_value,
        restart_required=restart_required,
    )


def _derive_secret_name(provider_name: str, suffix: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", provider_name).upper().strip("_")
    if not slug:
        slug = "PROVIDER"
    clean_suffix = suffix.upper().lstrip("_")
    return f"{slug}_{clean_suffix}" if clean_suffix else slug


def _normalize_secret_pointer(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", trimmed).upper().strip("_")
    if not normalized:
        raise SystemConfigurationError("Secret names must include letters or numbers.")
    return normalized


def get_configurable_models() -> List[ModelInfo]:
    """Return model configuration entries with availability metadata."""
    config_status = validate_settings()
    models_config = get_models_config()
    issue_messages = {
        issue.name.split(':', 1)[1]: issue.message
        for issue in config_status.issues
        if issue.name.startswith('model:')
    }
    return [
        _build_model_info(name, config, config_status.model_availability, issue_messages)
        for name, config in models_config.items()
    ]


def upsert_configurable_model(model_name: str, payload: ModelConfigRequest) -> ModelInfo:
    """Create or update a model mapping, enforcing editability rules."""
    try:
        updated = upsert_model_mapping(
            name=model_name,
            provider=payload.provider,
            model_string=payload.model_string,
            capabilities=payload.capabilities,
            dimensions=payload.dimensions,
            description=payload.description,
        )
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration()
    config_status = reload_result.status
    issue_messages = {
        issue.name.split(':', 1)[1]: issue.message
        for issue in config_status.issues
        if issue.name.startswith('model:')
    }

    logger.info(
        "Model alias upserted",
        data={"alias": model_name, "provider": payload.provider},
    )
    return _build_model_info(model_name, updated, config_status.model_availability, issue_messages)


def delete_configurable_model(model_name: str) -> OperationResult:
    """Remove a model mapping if permitted."""
    try:
        delete_model_mapping(model_name)
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration()
    logger.info("Model alias deleted", data={"alias": model_name})
    return OperationResult(
        success=True,
        message=f"Model '{model_name}' removed.",
        restart_required=reload_result.restart_required,
    )


def get_configurable_providers() -> List[ProviderInfo]:
    """Return provider configurations suitable for user editing."""
    providers_config = get_providers_config()
    return [
        _build_provider_info(name, config)
        for name, config in providers_config.items()
    ]


def upsert_configurable_provider(provider_name: str, payload: ProviderConfigRequest) -> ProviderInfo:
    """Create or update a provider configuration entry."""
    providers_config = get_providers_config()
    existing_config = providers_config.get(provider_name)

    # Only reference existing secret names; actual secret values are managed via the Secrets form.
    existing_api_key = None
    existing_base_url = None
    if existing_config:
        if hasattr(existing_config, "api_key"):
            existing_api_key = existing_config.api_key
            existing_base_url = getattr(existing_config, "base_url", None)
        else:
            existing_api_key = existing_config.get('api_key')
            existing_base_url = existing_config.get('base_url')

    fields_set = getattr(payload, "model_fields_set", set())

    if "api_key" in fields_set:
        api_key = _normalize_secret_pointer(payload.api_key)
    else:
        api_key = existing_api_key

    if "base_url" in fields_set:
        base_url = _normalize_secret_pointer(payload.base_url)
    else:
        base_url = existing_base_url

    try:
        updated = upsert_provider_config(
            name=provider_name,
            api_key=api_key,
            base_url=base_url,
        )
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration()

    logger.info(
        "Provider upserted",
        data={
            "alias": provider_name,
            "has_api_key": bool(api_key),
            "has_base_url": bool(base_url),
        },
    )
    return _build_provider_info(
        provider_name,
        updated,
        restart_required=reload_result.restart_required,
    )


def delete_configurable_provider(provider_name: str) -> OperationResult:
    """Remove a provider configuration if permitted."""
    try:
        delete_provider_config(provider_name)
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration()
    logger.info("Provider deleted", data={"alias": provider_name})
    return OperationResult(
        success=True,
        message=f"Provider '{provider_name}' removed.",
        restart_required=reload_result.restart_required,
    )


def _collect_known_secret_names() -> set[str]:
    names: set[str] = set()

    providers = get_providers_config()
    for config in providers.values():
        api_key = getattr(config, "api_key", None)
        if api_key and isinstance(api_key, str) and api_key.lower() != "null":
            names.add(api_key)
        base_url = getattr(config, "base_url", None)
        if base_url and isinstance(base_url, str) and "://" not in base_url:
            names.add(base_url)

    tools = get_tools_config()
    for tool in tools.values():
        if hasattr(tool, "required_secret_keys"):
            names.update(tool.required_secret_keys())

    names.add("LOGFIRE_TOKEN")
    return names


def list_secrets() -> List[SecretInfo]:
    entries = list_secret_entries()
    recorded_entries = {entry.name: entry for entry in entries}
    ordered_names: List[str] = [entry.name for entry in entries]

    known_names = _collect_known_secret_names()
    seen = set(ordered_names)
    for name in sorted(known_names):
        if name not in seen:
            ordered_names.append(name)
            seen.add(name)

    secrets: List[SecretInfo] = []
    for name in ordered_names:
        entry = recorded_entries.get(name)
        if entry is not None:
            has_value = entry.has_value
            stored = entry.is_overlay
        else:
            has_value = secret_has_value(name)
            stored = False
        secrets.append(SecretInfo(name=name, has_value=has_value, stored=stored))

    return secrets


def update_secret(request: SecretUpdateRequest) -> OperationResult:
    if not request.name:
        raise SystemConfigurationError("Secret name is required.")

    value = (request.value or "").strip()
    if value:
        set_secret_value(request.name, value)
    else:
        remove_secret(request.name)

    reload_result = reload_configuration()

    action = "Updated" if value else "Cleared"
    logger.info(
        "Secret updated",
        data={"name": request.name, "has_value": bool(value)},
    )
    return OperationResult(
        success=True,
        message=f"{action} {request.name}.",
        restart_required=reload_result.restart_required,
    )


def delete_secret_entry(name: str) -> OperationResult:
    if not name:
        raise SystemConfigurationError("Secret name is required.")

    delete_secret(name)
    reload_result = reload_configuration()

    logger.info("Secret deleted", data={"name": name})
    return OperationResult(
        success=True,
        message=f"Deleted {name}.",
        restart_required=reload_result.restart_required,
    )


async def execute_workflow_manually(
    global_id: str,
    expect_failure: bool = False,
    *,
    vault_name: str | None = None,
) -> Dict[str, Any]:
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

        if global_id.startswith("system/"):
            task = await _start_system_workflow_template(
                global_id=global_id,
                vault_name=vault_name,
                expect_failure=expect_failure,
            )
            logger.info(
                "System workflow template execution started",
                data={
                    "global_id": global_id,
                    "vault_name": vault_name or "",
                    "task_id": task.task_id,
                    "status": task.status,
                },
            )
            return _workflow_started_response(global_id=global_id, task=task)

        try:
            runtime = get_runtime_context()
            task = await runtime.workflow_governor.start_workflow(
                global_id=global_id,
                source=ExecutionTaskSource.API,
                expect_failure=expect_failure,
                background_tasks=runtime.background_tasks,
            )
        except Exception as workflow_error:
            if isinstance(workflow_error, ValueError):
                raise
            raise SystemConfigurationError(f"Workflow execution failed for '{global_id}': {str(workflow_error)}")

        logger.info(
            "Workflow execution started",
            data={
                "global_id": global_id,
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
    task,
) -> Dict[str, Any]:
    """Build the API response for an accepted manual workflow run."""
    return {
        "success": True,
        "global_id": global_id,
        "status": task.status,
        "task": _execution_task_info(task).model_dump(mode="python"),
        "message": f"Workflow '{global_id}' started as task {task.task_id}.",
    }


async def _start_system_workflow_template(
    *,
    global_id: str,
    vault_name: str | None,
    expect_failure: bool,
) -> object:
    """Start one system workflow template against an explicit vault scope."""
    if not vault_name:
        raise ValueError("vault_name is required to run a system workflow template.")
    runtime = get_runtime_context()
    task = await runtime.task_coordinator.create_queued_task(
        kind=ExecutionTaskKind.WORKFLOW,
        scope=workflow_vault_scope(vault_name),
        source=ExecutionTaskSource.API,
        label=global_id,
        metadata={
            "workflow_id": global_id,
            "vault": vault_name,
            "system_template": global_id.split("/", 1)[1] if "/" in global_id else global_id,
        },
    )

    async def _run() -> None:
        try:
            await _execute_system_workflow_template(
                global_id=global_id,
                vault_name=vault_name,
                expect_failure=expect_failure,
                task_id=task.task_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return

    def _spawn() -> None:
        background_task = asyncio.create_task(_run(), context=contextvars.Context())
        runtime.background_tasks.add(background_task)
        background_task.add_done_callback(runtime.background_tasks.discard)

    asyncio.get_running_loop().call_soon(_spawn, context=contextvars.Context())
    return task


async def _execute_system_workflow_template(
    *,
    global_id: str,
    vault_name: str | None,
    expect_failure: bool,
    task_id: str | None = None,
) -> Dict[str, Any]:
    """Execute one system workflow template against an explicit vault scope."""
    if not vault_name:
        raise ValueError("vault_name is required to run a system workflow template.")
    if "/" not in global_id:
        raise ValueError(f"Invalid global_id format. Expected 'system/name', got: {global_id}")

    _system_prefix, template_name = global_id.split("/", 1)
    if not template_name or template_name.startswith("/") or ".." in template_name:
        raise ValueError("Invalid system workflow template name.")

    runtime = get_runtime_context()
    vault_path = Path(runtime.config.data_root) / vault_name
    if not vault_path.exists() or not vault_path.is_dir():
        raise ValueError(f"Vault not found: {vault_name}")

    template = next(
        (
            record
            for record in list_system_workflow_templates(runtime.config.system_root)
            if (record.name[:-3] if record.name.endswith(".md") else record.name) == template_name
        ),
        None,
    )
    if template is None or not template.path:
        raise ValueError(f"System workflow template not found: {global_id}")

    scoped_workflow_id = f"{vault_name}/system/{template_name}"
    started = perf_counter()
    task_context = (
        runtime.task_coordinator.track_existing_task(task_id)
        if task_id
        else runtime.task_coordinator.track_current_task(
            kind=ExecutionTaskKind.WORKFLOW,
            scope=workflow_vault_scope(vault_name),
            source=ExecutionTaskSource.API,
            label=global_id,
            metadata={
                "workflow_id": global_id,
                "scoped_workflow_id": scoped_workflow_id,
                "vault": vault_name,
                "system_template": template_name,
            },
        )
    )
    async with task_context as task:
        await runtime.task_coordinator.mark_started(task.task_id)
        await runtime.task_coordinator.update_metadata(
            task.task_id,
            {"scoped_workflow_id": scoped_workflow_id},
        )
        execution_result = await run_authoring_template(
            workflow_id=scoped_workflow_id,
            file_path=str(template.path),
            expect_failure=expect_failure,
        )
        elapsed = perf_counter() - started
        terminal_status = str(getattr(execution_result, "status", "completed") or "completed")
        terminal_reason = str(getattr(execution_result, "reason", "") or "")
        result = {
            "success": True,
            "global_id": global_id,
            "status": terminal_status,
            "execution_time_seconds": elapsed,
            "output_files": [],
            "reason": terminal_reason or None,
            "details": [f"task_id: {task.task_id}", f"vault_scope: {vault_name}"],
            "message": (
                f"System workflow template '{global_id}' executed for vault "
                f"'{vault_name}' with status '{terminal_status}'."
            ),
        }
        await runtime.task_coordinator.update_metadata(
            task.task_id,
            {"workflow_result": result},
        )
        if terminal_status == "skipped":
            await runtime.task_coordinator.mark_skipped(task.task_id, reason=terminal_reason or None)
        elif terminal_status == "failed":
            await runtime.task_coordinator.mark_failed(task.task_id, reason=terminal_reason or None)
        elif terminal_status == "cancelled":
            await runtime.task_coordinator.mark_cancelled(task.task_id, reason=terminal_reason or None)
        elif terminal_status == "timed_out":
            await runtime.task_coordinator.mark_timed_out(task.task_id, reason=terminal_reason or None)
        return result


async def get_metadata() -> MetadataResponse:
    """
    Get metadata for UI configuration (vaults, models, tools).

    Returns:
        MetadataResponse with vaults, models, and tools
    """
    # Get vaults from runtime context
    vault_data = _get_workflow_loader().get_vault_info()
    vaults = list(vault_data.keys())

    # Evaluate configuration status for availability metadata
    config_status = validate_settings()

    # Get models from settings
    models_config = get_models_config()
    model_issue_messages = {
        issue.name.split(':', 1)[1]: issue.message
        for issue in config_status.issues
        if issue.name.startswith('model:')
    }

    models = []
    for name, config in models_config.items():
        if hasattr(config, "provider"):
            provider = config.provider
            model_string = config.model_string
            capabilities = list(getattr(config, "capabilities", ["text"]) or ["text"])
            dimensions = getattr(config, "dimensions", None)
            user_editable = getattr(config, "user_editable", True)
            description = getattr(config, "description", None)
        else:
            provider = config['provider']
            model_string = config['model_string']
            capabilities = list(config.get("capabilities", ["text"]) or ["text"])
            dimensions = config.get("dimensions")
            user_editable = config.get('user_editable', True)
            description = config.get('description')

        models.append(
            ModelInfo(
                name=name,
                provider=provider,
                model_string=model_string,
                capabilities=capabilities,
                dimensions=dimensions,
                available=config_status.model_availability.get(name, True),
                user_editable=user_editable,
                description=description,
                status_message=model_issue_messages.get(name),
            )
        )

    # Get tools from settings
    tools_config = get_tools_config()
    tools = []
    for name, config in tools_config.items():
        if hasattr(config, "description"):
            description = config.description or ""
            if hasattr(config, "required_secret_keys"):
                requires_secrets = list(config.required_secret_keys())
            else:
                requires_secrets = list(getattr(config, "requires_secrets", []) or getattr(config, "requires_env", []) or [])
            user_editable = getattr(config, "user_editable", False)
            chat_visible = getattr(config, "chat_visible", True)
        else:
            description = config.get('description', '')
            requires_secrets = list(config.get('requires_secrets') or config.get('requires_env') or [])
            user_editable = config.get('user_editable', False)
            chat_visible = config.get('chat_visible', True)

        if not chat_visible:
            continue

        tools.append(
            ToolInfo(
                name=name,
                description=description,
                requires_secrets=requires_secrets,
                available=config_status.tool_availability.get(name, True),
                user_editable=user_editable,
                chat_visible=chat_visible,
            )
        )

    default_context_script = None
    try:
        default_entry = get_general_settings().get("default_context_script")
        if default_entry and default_entry.value:
            default_context_script = str(default_entry.value).strip() or None
    except Exception:
        default_context_script = None

    default_chat_tools: list[str] = []
    try:
        default_tools_entry = get_general_settings().get("default_chat_tools")
        raw_default_tools = getattr(default_tools_entry, "value", [])
        if isinstance(raw_default_tools, list):
            default_chat_tools = [
                str(tool_name).strip()
                for tool_name in raw_default_tools
                if str(tool_name).strip()
            ]
    except Exception:
        default_chat_tools = []

    return MetadataResponse(
        vaults=vaults,
        models=models,
        tools=tools,
        settings={
            "default_chat_tools": default_chat_tools,
            "default_model_thinking": getattr(
                get_general_settings().get("default_model_thinking"), "value", "default"
            ),
            "auto_cache_max_tokens": getattr(
                get_general_settings().get("auto_cache_max_tokens"), "value", 0
            )
        },
        default_context_script=default_context_script,
    )
