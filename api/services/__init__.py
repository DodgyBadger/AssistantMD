"""
Service layer for API operations.
Handles business logic for status reporting, vault management, etc.
"""

import hashlib
import json
import mimetypes
import re
import shutil
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart
from sqlalchemy import func, select

from core.activity_log import iter_activity_export, query_activity_log
from core.authoring.template_discovery import (
    list_system_workflow_templates,
    list_templates,
    seed_system_templates,
)
from core.chat import export_chat_transcript, remove_chat_transcript_exports
from core.chat.chat_store import StoredChatSession
from core.chat.compaction import compact_chat_history, get_compaction_status
from core.chat.deferred_reviews import (
    DeferredReviewError,
    StoredDeferredReview,
    attach_deferred_review_task,
    deferred_review_conflicts,
    get_deferred_review,
    get_pending_deferred_review,
    mark_deferred_review_submitted,
    mark_deferred_review_terminal,
)
from core.chat.edit_proposals import (
    EditProposalError,
    get_edit_proposal,
)
from core.chat.task_execution import start_deferred_review_resume_task
from core.chat.workspace import normalize_workspace_path
from core.constants import ASSISTANTMD_ROOT_DIR, INLINE_EDIT_DENIAL_MESSAGE
from core.llm.openai_auth import (
    openai_oauth_enabled_from_settings,
    openai_provider_api_key_available,
    openai_provider_base_url_available,
    resolve_openai_auth,
)
from core.llm.openai_oauth import (
    OpenAIOAuthStateError,
    clear_openai_oauth_state,
    complete_openai_oauth,
    complete_openai_oauth_from_redirect,
    get_openai_oauth_status,
    is_openai_oauth_internal_secret,
    poll_openai_oauth_device_code,
    start_openai_oauth_device_code,
)
from core.llm.openai_oauth import (
    start_openai_oauth as start_openai_oauth_attempt,
)
from core.llm.thinking import ThinkingValue, normalize_thinking_value
from core.memory.session_summary import SessionSummaryStore
from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSource,
    chat_session_scope,
    compaction_task_label,
    workflow_vault_scope,
)
from core.runtime.paths import (
    get_system_root,
    resolve_bootstrap_data_root,
    resolve_bootstrap_system_root,
    set_bootstrap_roots,
)
from core.runtime.reload_service import reload_configuration
from core.runtime.state import RuntimeStateError, get_runtime_context
from core.runtime.task_runner import ExecutionTaskSpec
from core.scheduling.job_history import get_scheduler_job_history
from core.scheduling.jobs import setup_scheduler_jobs
from core.scheduling.system_jobs import SYSTEM_JOB_IDS
from core.settings import (
    SettingsError,
    get_default_chat_mode,
    validate_settings,
)
from core.settings.config_editor import (
    delete_model_mapping,
    delete_provider_config,
    list_general_settings,
    update_general_setting,
    upsert_model_mapping,
    upsert_provider_config,
)
from core.settings.secrets_store import (
    delete_secret,
    get_secret_value,
    list_secret_entries,
    remove_secret,
    secret_has_value,
    set_secret_value,
)
from core.settings.store import (
    SETTINGS_TEMPLATE,
    get_active_settings_path,
    get_disabled_tool_names,
    get_enabled_tool_names,
    get_enabled_tools_config,
    get_general_settings,
    get_models_config,
    get_providers_config,
    get_tools_config,
)
from core.settings.upgrades import upgrade_settings_mapping
from core.system_migrations import (
    get_system_migration_status as get_registered_system_migration_status,
)
from core.system_migrations import (
    run_system_migrations as run_registered_system_migrations,
)
from core.tools.workflow_run import WorkflowRun
from core.utils.frontmatter import upsert_frontmatter_key
from core.vault_state.activity import VaultActivityContext, use_vault_activity
from core.vault_state.activity_rollback import (
    ActivityRollbackPlan,
    ActivityRollbackUnavailable,
    execute_activity_rollback,
    preview_activity_rollback,
)
from core.vault_state.cleanup import cleanup_expired_vault_state
from core.vault_state.file_mutations import (
    VaultMutationRejected,
    replace_vault_file_content,
    restore_vault_file,
    write_vault_file,
    write_vault_file_bytes,
)
from core.vault_state.file_operations import (
    VaultFileOperationRejected,
    VaultFileOperationResult,
    delete_vault_path_operation,
    make_vault_directory_operation,
    move_vault_directory_operation,
    move_vault_path_operation,
    replace_full_text_content,
)
from core.vault_state.models import VaultFile, VaultFileEvent
from core.vault_state.pathing import (
    VaultRootResolutionError,
    normalize_vault_relative_path,
    resolve_configured_vault_root,
    resolve_vault_relative_path,
)
from core.vault_state.service import VaultStateService
from core.vector import VectorService
from core.workflow_runs import WorkflowRunRecord

from ..exceptions import APIException, SystemConfigurationError
from ..models import (
    ChatHistoryCompactionResponse,
    ChatHistoryCompactionStatusResponse,
    ChatSessionDetailResponse,
    ChatSessionExportResponse,
    ChatSessionFailureInfo,
    ChatSessionForkResponse,
    ChatSessionInfo,
    ChatSessionMessageInfo,
    ChatSessionsPurgeResponse,
    ChatSessionToolEventInfo,
    ChatWorkspaceInfo,
    ConfigurationIssueInfo,
    ConfigurationStatusInfo,
    DeferredReviewCallInfo,
    DeferredReviewResponse,
    DeferredReviewSubmitResponse,
    EditProposalResponse,
    MetadataResponse,
    ModelConfigRequest,
    ModelInfo,
    OpenAIOAuthCompleteRequest,
    OpenAIOAuthDeviceCheckResponse,
    OpenAIOAuthDeviceStartResponse,
    OpenAIOAuthStartRequest,
    OpenAIOAuthStartResponse,
    OperationResult,
    ProviderConfigRequest,
    ProviderInfo,
    SchedulerInfo,
    SecretInfo,
    SecretUpdateRequest,
    SettingInfo,
    SettingUpdateRequest,
    StatusResponse,
    SystemInfo,
    SystemLogResponse,
    SystemMigrationRunResponse,
    SystemMigrationStatusResponse,
    SystemMigrationTargetInfo,
    SystemSettingsResponse,
    SystemTemplateSeedResponse,
    SystemWorkflowTemplateSummary,
    TemplateInfo,
    ToolInfo,
    VaultActivityResponse,
    VaultActivityRollbackIssueInfo,
    VaultActivityRollbackPathInfo,
    VaultActivityRollbackPreviewResponse,
    VaultActivityRollbackResponse,
    VaultDirectoryInfo,
    VaultDirectoryListResponse,
    VaultFileReferenceInfo,
    VaultFileReferenceListResponse,
    VaultFileResponse,
    VaultFileRevisionInfo,
    VaultFileRevisionResponse,
    VaultFileRevisionRestoreResponse,
    VaultInfo,
    VaultPathMutationResponse,
    VaultPathResolutionInfo,
    VaultPathResolveResponse,
    VaultStateCleanupResponse,
    WorkflowEnabledResponse,
    WorkflowFileResponse,
    WorkflowSummary,
)
from ..models import (
    ConfigurationError as APIConfigurationError,
)
from ..utils import generate_session_id
from .execution_tasks import (
    _execution_task_info,
    cancel_chat_session_task,
    cancel_execution_task,
    get_active_chat_task,
    get_execution_task,
    list_execution_tasks,
    list_workflow_tasks,
)
from .ingestion import import_url_direct, scan_import_folder
from .maintenance import cleanup_goals, purge_expired_cache
from .shared import chat_store as _chat_store
from .shared import (
    get_vault_path as _get_vault_path,
)
from .shared import (
    get_workflow_loader as _get_workflow_loader,
)
from .shared import logger
from .vault_activity import (
    SnapshotFileResponse,
    cleanup_vault_state,
    get_vault_activity,
    get_vault_activity_rollback_preview,
    get_vault_snapshot_file,
    rollback_vault_activity,
)

_VAULT_FILE_REFERENCE_LIMIT = 100
_VAULT_FILE_READ_MAX_BYTES = 2 * 1024 * 1024
_NON_TEXT_MEDIA_TYPE_PREFIXES = (
    "application/vnd.ms-",
    "application/vnd.openxmlformats-officedocument.",
    "audio/",
    "font/",
    "image/",
    "video/",
)
_NON_TEXT_MEDIA_TYPES = {
    "application/epub+zip",
    "application/gzip",
    "application/octet-stream",
    "application/pdf",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/x-7z-compressed",
    "application/x-bzip2",
    "application/x-rar-compressed",
    "application/x-tar",
    "application/zip",
}


def get_enabled_chat_tool_names() -> list[str]:
    """Return app-wide enabled tools that may be exposed to chat agents."""
    configs = get_enabled_tools_config()
    return [
        name
        for name in get_enabled_tool_names()
        if name in configs and getattr(configs[name], "chat_visible", True)
    ]


# Global variable to track system startup time
_system_startup_time: datetime | None = None


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


def resolve_chat_session_for_request(
    *, requested_session_id: str | None, vault_name: str
) -> str:
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
    try:
        return normalize_workspace_path(path)
    except ValueError as exc:
        message = str(exc)
        error_type = "InvalidWorkspacePath"
        if "relative to the vault" in message:
            details = {"path": path}
        elif "cannot contain '..'" in message:
            details = {"path": path}
        else:
            details = {"path": path}
        raise APIException(
            status_code=400,
            error_type=error_type,
            message=message,
            details=details,
        ) from exc


def resolve_vault_root(vault_name: str) -> Path:
    """Return an existing vault root for API file operations."""
    runtime = get_runtime_context()
    try:
        return resolve_configured_vault_root(
            data_root=runtime.config.data_root,
            vault_name=vault_name,
        )
    except VaultRootResolutionError as exc:
        status_code = 404 if exc.code == "vault_not_found" else 400
        error_type = {
            "invalid_vault_name": "InvalidVaultName",
            "vault_root_escapes_data_root": "VaultRootEscapesDataRoot",
            "vault_not_found": "VaultNotFound",
        }.get(exc.code, "InvalidVaultName")
        raise APIException(
            status_code=status_code,
            error_type=error_type,
            message=str(exc),
            details={"vault_name": exc.vault_name},
        ) from exc


def _normalize_vault_file_path(path: str | None) -> str:
    raw_path = str(path or "").strip()
    slash_normalized = raw_path.replace("\\", "/")
    has_drive_prefix = (
        len(slash_normalized) >= 3
        and slash_normalized[0].isalpha()
        and slash_normalized[1:3] == ":/"
    )
    path_parts = slash_normalized.split("/")
    if (
        not raw_path
        or raw_path.startswith(("/", "\\"))
        or has_drive_prefix
        or any(part in {".", ".."} for part in path_parts)
        or any(ord(character) < 32 for character in raw_path)
        or len(raw_path) > 1000
    ):
        raise APIException(
            status_code=400,
            error_type="InvalidVaultFilePath",
            message="A safe vault-relative file path is required.",
            details={"path": raw_path[:100]},
        )
    normalized = normalize_vault_relative_path(raw_path)
    return normalized


def _resolve_vault_file_path(
    vault_name: str, path: str | None
) -> tuple[Path, str, Path]:
    """Resolve a vault-relative file path under an existing vault."""
    vault_root = resolve_vault_root(vault_name)
    normalized = _normalize_vault_file_path(path)
    try:
        resolved = resolve_vault_relative_path(
            vault_path=vault_root,
            path=normalized,
            markdown_only=False,
        )
    except ValueError as exc:
        raise APIException(
            status_code=400,
            error_type="InvalidVaultFilePath",
            message=str(exc),
            details={"path": path, "vault_name": vault_name},
        ) from exc
    return vault_root, normalized, resolved


def _datetime_from_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def _vault_file_response(
    *,
    vault_name: str,
    path: str,
    full_path: Path,
    content: str,
    message: str | None = None,
) -> VaultFileResponse:
    encoded = content.encode("utf-8")
    return VaultFileResponse(
        vault_name=vault_name,
        path=path,
        name=full_path.name,
        content=content,
        sha256=_sha256_text(content),
        size_bytes=len(encoded),
        modified_at=_datetime_from_mtime(full_path),
        media_type=mimetypes.guess_type(path)[0] or "text/plain",
        message=message,
    )


def get_vault_file(vault_name: str, path: str) -> VaultFileResponse:
    """Return editable text content for one vault file."""
    _, normalized, full_path = _resolve_vault_file_path(vault_name, path)
    if not full_path.exists():
        raise APIException(
            status_code=404,
            error_type="VaultFileNotFound",
            message=f"Vault file not found: {normalized}",
            details={"path": normalized, "vault_name": vault_name},
        )
    if not full_path.is_file():
        raise APIException(
            status_code=400,
            error_type="VaultPathNotFile",
            message=f"Vault path is not a file: {normalized}",
            details={"path": normalized, "vault_name": vault_name},
        )
    content = _read_editable_vault_text(
        full_path=full_path,
        path=normalized,
        vault_name=vault_name,
    )
    return _vault_file_response(
        vault_name=vault_name,
        path=normalized,
        full_path=full_path,
        content=content,
    )


def get_vault_file_revisions(
    *,
    vault_name: str,
    path: str,
    limit: int = 50,
) -> VaultFileRevisionResponse:
    """Return retained pre-mutation states for one exact vault file path."""
    _, normalized, _ = _resolve_vault_file_path(vault_name, path)
    revisions = VaultStateService().list_file_revisions(
        vault_name=vault_name,
        path=normalized,
        limit=limit,
    )
    return VaultFileRevisionResponse(
        vault_name=vault_name,
        path=normalized,
        revisions=[
            VaultFileRevisionInfo(
                snapshot_id=revision.snapshot_id,
                activity_id=revision.activity_id,
                activity_kind=revision.activity_kind,
                activity_source=revision.activity_source,
                activity_label=revision.activity_label,
                task_id=revision.task_id,
                path=revision.path,
                operation=revision.operation,
                exists=revision.exists,
                content_hash=revision.content_hash,
                snapshot_available=revision.snapshot_available,
                created_at=revision.created_at,
                expires_at=revision.expires_at,
            )
            for revision in revisions
        ],
    )


def restore_vault_file_revision(
    *,
    vault_name: str,
    snapshot_id: int,
    expected_sha256: str | None,
) -> VaultFileRevisionRestoreResponse:
    """Restore one retained exact-path revision as a new Explorer mutation."""
    service = VaultStateService()
    revision = service.get_file_revision(
        vault_name=vault_name,
        snapshot_id=snapshot_id,
    )
    if revision is None:
        raise APIException(
            status_code=404,
            error_type="VaultFileRevisionNotFound",
            message=f"Vault file revision not found or no longer retained: {snapshot_id}",
            details={"snapshot_id": snapshot_id, "vault_name": vault_name},
        )

    vault_root, normalized, full_path = _resolve_vault_file_path(
        vault_name,
        revision.path,
    )
    if full_path.exists() and not full_path.is_file():
        raise APIException(
            status_code=409,
            error_type="VaultFileConflict",
            message=f"Cannot restore over a directory: {normalized}",
            details={"path": normalized, "vault_name": vault_name},
        )

    if not revision.exists and not full_path.exists() and expected_sha256 is None:
        return VaultFileRevisionRestoreResponse(
            vault_name=vault_name,
            path=normalized,
            snapshot_id=snapshot_id,
            exists=False,
            sha256=None,
            message=f"{normalized} is already absent.",
        )

    content: bytes | None = None
    if revision.exists:
        snapshot = service.resolve_snapshot_file(snapshot_id)
        if snapshot is None:
            raise APIException(
                status_code=404,
                error_type="VaultFileRevisionNotFound",
                message=f"Revision content is no longer retained: {snapshot_id}",
                details={"snapshot_id": snapshot_id, "vault_name": vault_name},
            )
        content = snapshot.path.read_bytes()

    try:
        with _explorer_activity(label=f"Restore {normalized}"):
            mutation = restore_vault_file(
                vault_path=vault_root,
                path=normalized,
                content=content,
                expected_sha256=expected_sha256,
            )
    except VaultMutationRejected as exc:
        if exc.code in {"file_conflict", "file_not_found"}:
            raise APIException(
                status_code=409,
                error_type="VaultFileConflict",
                message="The file changed since its revision history was opened. Refresh and retry.",
                details={"path": normalized, "vault_name": vault_name},
            ) from exc
        raise

    return VaultFileRevisionRestoreResponse(
        vault_name=vault_name,
        path=normalized,
        snapshot_id=snapshot_id,
        exists=mutation.after_exists,
        sha256=mutation.after_hash,
        message=(
            f"Restored {normalized}."
            if mutation.after_exists
            else f"Restored the earlier absent state for {normalized}."
        ),
    )


def update_vault_file(
    *,
    vault_name: str,
    path: str,
    content: str,
    expected_sha256: str | None = None,
    create_if_missing: bool = False,
) -> VaultFileResponse:
    """Replace one vault text file after an optional content-hash check."""
    vault_root, normalized, full_path = _resolve_vault_file_path(vault_name, path)
    if not full_path.exists() or not full_path.is_file():
        if create_if_missing and not full_path.exists():
            with _explorer_activity(
                label=f"Create {normalized}",
            ):
                write_vault_file(
                    vault_path=vault_root,
                    path=normalized,
                    content=content,
                    fail_if_exists=True,
                    markdown_only=False,
                )
            return _vault_file_response(
                vault_name=vault_name,
                path=normalized,
                full_path=full_path,
                content=content,
                message=f"Created {normalized}.",
            )
        raise APIException(
            status_code=404,
            error_type="VaultFileNotFound",
            message=f"Vault file not found: {normalized}",
            details={"path": normalized, "vault_name": vault_name},
        )
    _read_editable_vault_text(
        full_path=full_path,
        path=normalized,
        vault_name=vault_name,
    )
    try:
        with _explorer_activity(
            label=f"Edit {normalized}",
        ):
            replace_full_text_content(
                vault_path=vault_root,
                path=normalized,
                content=content,
                operation="update_vault_file",
                expected_sha256=expected_sha256,
                markdown_only=False,
            )
    except VaultFileOperationRejected as exc:
        if exc.code == "file_not_text":
            raise APIException(
                status_code=415,
                error_type="VaultFileNotText",
                message=f"Vault file is not UTF-8 text: {normalized}",
                details={"path": normalized, "vault_name": vault_name},
            ) from exc
        if exc.code == "file_conflict":
            raise APIException(
                status_code=409,
                error_type="VaultFileConflict",
                message="Vault file changed since it was opened. Refresh and retry.",
                details={
                    "path": normalized,
                    "vault_name": vault_name,
                    "expected_sha256": exc.details.get("expected_sha256"),
                    "current_sha256": exc.details.get("actual_sha256"),
                },
            ) from exc
        raise APIException(
            status_code=400,
            error_type=exc.code,
            message=str(exc),
            details={"path": normalized, "vault_name": vault_name, **exc.details},
        ) from exc
    return _vault_file_response(
        vault_name=vault_name,
        path=normalized,
        full_path=full_path,
        content=content,
        message=f"Saved {normalized}.",
    )


def _read_editable_vault_text(*, full_path: Path, path: str, vault_name: str) -> str:
    """Return UTF-8 text or reject content that should not enter the inline editor."""
    try:
        size_bytes = full_path.stat().st_size
    except OSError as exc:
        raise APIException(
            status_code=500,
            error_type="VaultFileStatFailed",
            message=f"Failed to inspect vault file: {path}",
            details={"path": path, "vault_name": vault_name},
        ) from exc
    if size_bytes > _VAULT_FILE_READ_MAX_BYTES:
        raise APIException(
            status_code=413,
            error_type="VaultFileTooLarge",
            message=f"Vault file is too large for inline editing: {path}",
            details={
                "path": path,
                "vault_name": vault_name,
                "size_bytes": size_bytes,
                "max_bytes": _VAULT_FILE_READ_MAX_BYTES,
            },
        )
    media_type = (mimetypes.guess_type(path)[0] or "").lower()
    if media_type in _NON_TEXT_MEDIA_TYPES or media_type.startswith(
        _NON_TEXT_MEDIA_TYPE_PREFIXES
    ):
        raise _vault_file_not_text_error(
            path=path, vault_name=vault_name, media_type=media_type
        )
    try:
        raw = full_path.read_bytes()
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _vault_file_not_text_error(
            path=path, vault_name=vault_name, media_type=media_type
        ) from exc
    if b"\x00" in raw or any(
        byte < 32 and byte not in {8, 9, 10, 12, 13} for byte in raw
    ):
        raise _vault_file_not_text_error(
            path=path, vault_name=vault_name, media_type=media_type
        )
    return content


def _vault_file_not_text_error(
    *, path: str, vault_name: str, media_type: str
) -> APIException:
    return APIException(
        status_code=415,
        error_type="VaultFileNotText",
        message=f"Vault file is not editable as plain text: {path}",
        details={"path": path, "vault_name": vault_name, "media_type": media_type},
    )


def get_chat_edit_proposal(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
) -> EditProposalResponse:
    """Return one chat edit proposal artifact."""
    try:
        proposal = get_edit_proposal(
            vault_name=vault_name,
            session_id=session_id,
            artifact_ref=artifact_ref,
        )
    except EditProposalError as exc:
        raise _edit_proposal_api_error(exc) from exc
    return EditProposalResponse(**proposal)


def get_chat_deferred_review(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
) -> DeferredReviewResponse:
    """Return one deferred inline review request."""
    review = get_deferred_review(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
    )
    if review is None:
        raise APIException(
            status_code=404,
            error_type="DeferredReviewNotFound",
            message="Deferred review request was not found for this chat session.",
            details={
                "artifact_ref": artifact_ref,
                "session_id": session_id,
                "vault_name": vault_name,
            },
        )
    return _deferred_review_response(review)


def _deferred_review_response(review: StoredDeferredReview) -> DeferredReviewResponse:
    """Translate a stored deferred review into its API representation."""
    return DeferredReviewResponse(
        artifact_ref=review.artifact_ref,
        artifact_kind="deferred_tool_review",
        vault_name=review.vault_name,
        session_id=review.session_id,
        originating_task_id=review.originating_task_id,
        status=review.status,
        approvals=[
            DeferredReviewCallInfo(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                args=call.args,
            )
            for call in review.requests.approvals
        ],
        calls=[
            DeferredReviewCallInfo(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                args=call.args,
            )
            for call in review.requests.calls
        ],
        created_at=review.created_at,
        submitted_at=review.submitted_at,
        resumed_task_id=review.resumed_task_id,
    )


async def submit_chat_deferred_review(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
    decisions: list[dict[str, Any]],
) -> DeferredReviewSubmitResponse:
    """Submit deferred inline review decisions and start a resume task."""
    review = _require_pending_deferred_review(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
        decisions=decisions,
    )
    approvals = _build_deferred_review_approvals(
        review=review,
        decisions=decisions,
        artifact_ref=artifact_ref,
    )
    results = DeferredToolResults(approvals=approvals)
    tools, model, thinking, context_template, chat_mode = _deferred_resume_options(
        review.resume_config,
        artifact_ref=artifact_ref,
    )
    vault_path = str(resolve_vault_root(vault_name))
    conflicts = deferred_review_conflicts(
        review=review,
        approved_call_ids={
            tool_call_id
            for tool_call_id, decision in approvals.items()
            if not isinstance(decision, ToolDenied)
        },
        vault_path=vault_path,
    )
    if conflicts:
        raise APIException(
            status_code=409,
            error_type="DeferredReviewTargetConflict",
            message="A reviewed file changed while approval was pending.",
            details={"artifact_ref": artifact_ref, "conflicts": conflicts},
        )
    try:
        claimed = mark_deferred_review_submitted(
            vault_name=vault_name,
            session_id=session_id,
            artifact_ref=artifact_ref,
            results=results,
            resumed_task_id="",
        )
    except DeferredReviewError as exc:
        raise _deferred_review_api_error(exc) from exc
    try:
        started = await start_deferred_review_resume_task(
            vault_name=vault_name,
            vault_path=vault_path,
            session_id=session_id,
            review=claimed,
            deferred_tool_results=results,
            tools=tools,
            model=model,
            thinking=thinking,
            context_template=context_template,
            chat_mode=chat_mode,
        )
        updated = attach_deferred_review_task(
            vault_name=vault_name,
            session_id=session_id,
            artifact_ref=artifact_ref,
            resumed_task_id=started.task.task_id,
        )
    except Exception as exc:
        try:
            mark_deferred_review_terminal(
                vault_name=vault_name,
                session_id=session_id,
                artifact_ref=artifact_ref,
                status="failed",
                error={"error_type": type(exc).__name__, "message": str(exc)},
            )
        except DeferredReviewError:
            pass
        raise
    task = await get_execution_task(started.task.task_id)
    return DeferredReviewSubmitResponse(
        artifact_ref=updated.artifact_ref,
        status=updated.status,
        session_id=session_id,
        task=task,
    )


def _require_pending_deferred_review(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
    decisions: list[dict[str, Any]],
) -> StoredDeferredReview:
    review = get_deferred_review(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
    )
    if review is None:
        raise APIException(
            status_code=404,
            error_type="DeferredReviewNotFound",
            message="Deferred review request was not found for this chat session.",
            details={"artifact_ref": artifact_ref},
        )
    if review.status != "pending":
        raise APIException(
            status_code=409,
            error_type="DeferredReviewAlreadySubmitted",
            message="Deferred review request has already been submitted.",
            details={
                "artifact_ref": artifact_ref,
                "status": review.status,
                "resumed_task_id": review.resumed_task_id,
            },
        )
    if review.requests.calls:
        raise APIException(
            status_code=400,
            error_type="UnsupportedDeferredCallReview",
            message="Deferred external call review is not supported yet.",
            details={"artifact_ref": artifact_ref},
        )
    if not decisions:
        raise APIException(
            status_code=400,
            error_type="NoDeferredReviewDecisions",
            message="Choose at least one review decision.",
            details={"artifact_ref": artifact_ref},
        )

    known_ids = {str(call.tool_call_id) for call in review.requests.approvals}
    submitted_ids = [str(decision.get("tool_call_id") or "") for decision in decisions]
    duplicate_ids = sorted(
        call_id for call_id, count in Counter(submitted_ids).items() if count > 1
    )
    unknown_ids = sorted(
        call_id for call_id in submitted_ids if call_id not in known_ids
    )
    missing_ids = sorted(known_ids - set(submitted_ids))
    if duplicate_ids or unknown_ids or missing_ids:
        raise APIException(
            status_code=400,
            error_type="DeferredReviewDecisionMismatch",
            message="Review decisions must cover the pending deferred tool calls.",
            details={
                "artifact_ref": artifact_ref,
                "duplicate_tool_call_ids": duplicate_ids,
                "unknown_tool_call_ids": unknown_ids,
                "missing_tool_call_ids": missing_ids,
            },
        )
    return review


def _build_deferred_review_approvals(
    *,
    review: StoredDeferredReview,
    decisions: list[dict[str, Any]],
    artifact_ref: str,
) -> dict[str, bool | ToolApproved | ToolDenied]:
    calls_by_id = {str(call.tool_call_id): call for call in review.requests.approvals}
    approvals: dict[str, bool | ToolApproved | ToolDenied] = {}
    for decision in decisions:
        tool_call_id = str(decision.get("tool_call_id") or "")
        decision_value = str(decision.get("decision") or "")
        if decision_value == "deny":
            message = str(decision.get("message") or "").strip()
            denial_message = INLINE_EDIT_DENIAL_MESSAGE
            if message:
                denial_message = f"{denial_message} User reason: {message}"
            approvals[tool_call_id] = ToolDenied(denial_message)
            continue
        if decision_value != "approve":
            raise APIException(
                status_code=400,
                error_type="InvalidDeferredReviewDecision",
                message="Deferred review decision must be approve or deny.",
                details={"tool_call_id": tool_call_id, "decision": decision_value},
            )

        override_args = decision.get("override_args") or {}
        if not isinstance(override_args, dict):
            override_args = {}
        _validate_deferred_review_overrides(
            tool_call_id=tool_call_id,
            original_args=calls_by_id[tool_call_id].args_as_dict(),
            override_args=override_args,
            artifact_ref=artifact_ref,
        )
        approvals[tool_call_id] = (
            ToolApproved(
                override_args={
                    **calls_by_id[tool_call_id].args_as_dict(),
                    **override_args,
                }
            )
            if override_args
            else True
        )
    return approvals


def _validate_deferred_review_overrides(
    *,
    tool_call_id: str,
    original_args: dict[str, Any],
    override_args: dict[str, Any],
    artifact_ref: str,
) -> None:
    if not override_args:
        return
    operation = str(original_args.get("operation") or "").strip().lower()
    editable_args = {
        "write": {"content"},
        "append": {"content"},
        "replace_text": {"old_text", "new_text"},
        "edit_line": {"old_text", "new_text"},
        "move": {"destination"},
    }.get(operation, set())
    changed_immutable = sorted(
        key
        for key, value in override_args.items()
        if key not in editable_args and value != original_args.get(key)
    )
    if changed_immutable:
        raise APIException(
            status_code=400,
            error_type="DeferredReviewImmutableArgument",
            message="Review overrides cannot change the operation target or policy.",
            details={
                "artifact_ref": artifact_ref,
                "tool_call_id": tool_call_id,
                "immutable_arguments": changed_immutable,
            },
        )


def _deferred_resume_options(
    resume_config: dict[str, Any], *, artifact_ref: str
) -> tuple[list[str], str, ThinkingValue, str | None, str]:
    model = str(resume_config.get("model") or "").strip()
    if not model:
        raise APIException(
            status_code=500,
            error_type="DeferredReviewResumeConfigMissing",
            message="Deferred review request is missing the model needed to resume.",
            details={"artifact_ref": artifact_ref},
        )
    tools = [
        str(tool) for tool in resume_config.get("tools") or [] if str(tool).strip()
    ]
    thinking = normalize_thinking_value(
        resume_config.get("thinking"),
        source_name="stored deferred review thinking",
    )
    context_template = str(resume_config.get("context_template") or "").strip() or None
    chat_mode = str(resume_config.get("chat_mode") or "normal").strip() or "normal"
    return tools, model, thinking, context_template, chat_mode


def _edit_proposal_api_error(exc: EditProposalError) -> APIException:
    status_by_code = {
        "EditProposalNotFound": 404,
        "VaultFileNotFound": 404,
        "VaultFileConflict": 409,
        "EditTextMismatch": 409,
        "ProposalAlreadyApplied": 409,
        "ProposalDenied": 409,
        "VaultFileExists": 409,
        "VaultDestinationExists": 409,
        "InvalidPath": 400,
        "InvalidDestination": 400,
        "InvalidOperation": 400,
        "InvalidEdit": 400,
        "NoSelectedEdits": 400,
        "UnknownEdit": 400,
    }
    return APIException(
        status_code=status_by_code.get(exc.code, 400),
        error_type=exc.code,
        message=str(exc),
        details=exc.details,
    )


def _deferred_review_api_error(exc: DeferredReviewError) -> APIException:
    status_by_code = {
        "DeferredReviewNotFound": 404,
        "DeferredReviewAlreadySubmitted": 409,
        "DeferredReviewStateConflict": 409,
    }
    return APIException(
        status_code=status_by_code.get(exc.code, 400),
        error_type=exc.code,
        message=str(exc),
        details=exc.details,
    )


def _resolve_existing_vault_directory(
    *, vault_name: str, path: str | None
) -> tuple[str, Path]:
    """Return a normalized path and existing directory for picker browsing."""
    normalized_path = _normalize_workspace_path(path)
    vault_root = resolve_vault_root(vault_name)
    resolved = (
        (vault_root / normalized_path).resolve() if normalized_path else vault_root
    )
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


def list_vault_directories(
    vault_name: str, path: str | None = None
) -> VaultDirectoryListResponse:
    """Return child directories for one vault-relative path."""
    base_path, base_dir = _resolve_existing_vault_directory(
        vault_name=vault_name, path=path
    )
    vault_root = resolve_vault_root(vault_name)
    directories: list[VaultDirectoryInfo] = []
    for child in sorted(base_dir.iterdir(), key=lambda item: item.name.lower()):
        if not _is_workspace_picker_directory(child):
            continue
        try:
            relative = child.resolve().relative_to(vault_root).as_posix()
        except ValueError:
            continue
        has_children = any(
            _is_workspace_picker_directory(grandchild) for grandchild in child.iterdir()
        )
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
    return (
        path.is_dir()
        and not path.name.startswith(".")
        and path.name != ASSISTANTMD_ROOT_DIR
    )


def list_vault_file_references(
    *,
    vault_name: str,
    path: str | None = None,
    workspace_path: str | None = None,
    query: str | None = None,
    scope: str = "workspace",
    limit: int = _VAULT_FILE_REFERENCE_LIMIT,
    offset: int = 0,
) -> VaultFileReferenceListResponse:
    """Return file/folder candidates for chat reference insertion."""
    vault_root = resolve_vault_root(vault_name)
    normalized_workspace = _normalize_workspace_path(workspace_path)
    normalized_scope: Literal["workspace", "vault"] = (
        scope if scope in {"workspace", "vault"} else "workspace"
    )
    normalized_query = (query or "").strip().lower()
    bounded_limit = min(
        max(int(limit or _VAULT_FILE_REFERENCE_LIMIT), 1), _VAULT_FILE_REFERENCE_LIMIT
    )
    bounded_offset = max(int(offset or 0), 0)

    if normalized_query:
        base_relative = normalized_workspace if normalized_scope == "workspace" else ""
        base_dir = resolve_vault_relative_path(
            vault_path=vault_root, path=base_relative
        )
        if not base_dir.exists() or not base_dir.is_dir():
            base_relative = ""
            base_dir = vault_root
        items, truncated = _search_vault_file_references(
            vault_root=vault_root,
            base_dir=base_dir,
            workspace_path=normalized_workspace,
            query=normalized_query,
            limit=bounded_limit,
        )
        return VaultFileReferenceListResponse(
            vault_name=vault_name,
            path=base_relative,
            workspace_path=normalized_workspace,
            query=normalized_query,
            scope=normalized_scope,
            items=items,
            truncated=truncated,
            next_offset=None,
        )

    base_relative = _normalize_workspace_path(path)
    if not base_relative and normalized_scope == "workspace":
        base_relative = normalized_workspace
    base_path, base_dir = _resolve_existing_vault_directory(
        vault_name=vault_name, path=base_relative
    )
    items, truncated = _list_vault_file_reference_children(
        vault_root=vault_root,
        base_dir=base_dir,
        workspace_path=normalized_workspace,
        limit=bounded_limit,
        offset=bounded_offset,
    )
    return VaultFileReferenceListResponse(
        vault_name=vault_name,
        path=base_path,
        workspace_path=normalized_workspace,
        query="",
        scope=normalized_scope,
        truncated=truncated,
        next_offset=bounded_offset + len(items) if truncated else None,
        items=items,
    )


def resolve_vault_path_references(
    *,
    vault_name: str,
    paths: list[str],
    workspace_path: str | None = None,
) -> VaultPathResolveResponse:
    """Resolve rendered chat path candidates without guessing recursively."""
    vault_root = resolve_vault_root(vault_name)
    normalized_workspace = _normalize_workspace_path(workspace_path)
    workspace_root: Path | None = None
    if normalized_workspace:
        candidate_workspace = resolve_vault_relative_path(
            vault_path=vault_root,
            path=normalized_workspace,
        )
        if candidate_workspace.is_dir():
            workspace_root = candidate_workspace

    items: list[VaultPathResolutionInfo] = []
    seen: set[str] = set()
    for raw_path in paths:
        requested_path = _normalize_chat_reference_candidate(raw_path)
        if not requested_path or requested_path in seen:
            continue
        seen.add(requested_path)

        resolved_item = None
        if "/" not in requested_path and workspace_root is not None:
            workspace_candidate = resolve_vault_relative_path(
                vault_path=workspace_root,
                path=requested_path,
            )
            resolved_item = _resolved_chat_path_item(
                vault_root=vault_root,
                requested_path=requested_path,
                candidate=workspace_candidate,
                source="workspace",
            )
        if resolved_item is None:
            vault_candidate = resolve_vault_relative_path(
                vault_path=vault_root,
                path=requested_path,
            )
            resolved_item = _resolved_chat_path_item(
                vault_root=vault_root,
                requested_path=requested_path,
                candidate=vault_candidate,
                source="vault",
            )
        items.append(
            resolved_item
            or VaultPathResolutionInfo(
                requested_path=requested_path,
                path=requested_path,
                kind="missing",
                source="missing",
            )
        )

    return VaultPathResolveResponse(
        vault_name=vault_name,
        workspace_path=normalized_workspace,
        items=items,
    )


def mutate_vault_path(
    *,
    vault_name: str,
    operation: str,
    path: str,
    destination: str = "",
    content: str = "",
) -> VaultPathMutationResponse:
    """Apply one direct explorer mutation through shared vault operations."""
    vault_root, normalized, full_path = _resolve_vault_file_path(vault_name, path)
    with _explorer_activity(
        label=f"{operation.replace('_', ' ').title()} {normalized}",
    ):
        return _mutate_vault_path_attributed(
            vault_name=vault_name,
            vault_root=vault_root,
            normalized=normalized,
            full_path=full_path,
            operation=operation,
            destination=destination,
            content=content,
        )


def upload_vault_file(
    *,
    vault_name: str,
    path: str,
    content: bytes,
) -> VaultPathMutationResponse:
    """Create one binary-safe vault file from an Explorer upload."""
    vault_root, normalized, _ = resolve_vault_upload_target(
        vault_name=vault_name,
        path=path,
    )

    with _explorer_activity(label=f"Upload {normalized}"):
        try:
            mutation = write_vault_file_bytes(
                vault_path=vault_root,
                path=normalized,
                content=content,
                fail_if_exists=True,
                warn_without_task=False,
            )
        except VaultMutationRejected as exc:
            raise _vault_path_mutation_error(
                exc,
                vault_name=vault_name,
                path=normalized,
            ) from exc

    logger.info(
        "Vault Explorer upload completed",
        data={
            "event": "vault_explorer_upload_completed",
            "vault_name": vault_name,
            "path": normalized,
            "size_bytes": len(content),
            "event_sequence": mutation.event_sequence,
        },
    )
    return VaultPathMutationResponse(
        operation="upload",
        path=normalized,
        destination="",
        kind="file",
        message=f"Uploaded {normalized}.",
        metadata={
            "size_bytes": len(content),
            "task_id": mutation.task_id,
            "vault_id": mutation.vault_id,
            "event_sequence": mutation.event_sequence,
        },
    )


def resolve_vault_upload_target(
    *,
    vault_name: str,
    path: str,
) -> tuple[Path, str, Path]:
    """Resolve one create-only upload target inside a configured vault."""
    vault_root, normalized, full_path = _resolve_vault_file_path(vault_name, path)
    if full_path.exists():
        raise APIException(
            status_code=409,
            error_type="VaultPathExists",
            message=f"Vault path already exists: {normalized}",
            details={"path": normalized, "vault_name": vault_name},
        )
    return vault_root, normalized, full_path


def _mutate_vault_path_attributed(
    *,
    vault_name: str,
    vault_root: Path,
    normalized: str,
    full_path: Path,
    operation: str,
    destination: str,
    content: str,
) -> VaultPathMutationResponse:
    """Apply an explorer mutation under an established activity context."""
    if operation == "create_file":
        if full_path.exists():
            raise APIException(
                status_code=409,
                error_type="VaultPathExists",
                message=f"Vault path already exists: {normalized}",
                details={"path": normalized, "vault_name": vault_name},
            )
        try:
            mutation = write_vault_file(
                vault_path=vault_root,
                path=normalized,
                content=content,
                fail_if_exists=True,
                markdown_only=False,
            )
        except VaultMutationRejected as exc:
            raise _vault_path_mutation_error(
                exc, vault_name=vault_name, path=normalized
            ) from exc
        return VaultPathMutationResponse(
            operation=operation,
            path=normalized,
            destination="",
            kind="file",
            message=f"Created {normalized}.",
            metadata={
                "task_id": mutation.task_id,
                "vault_id": mutation.vault_id,
                "event_sequence": mutation.event_sequence,
            },
        )

    if operation == "create_directory":
        if full_path.exists():
            raise APIException(
                status_code=409,
                error_type="VaultPathExists",
                message=f"Vault path already exists: {normalized}",
                details={"path": normalized, "vault_name": vault_name},
            )
        result = make_vault_directory_operation(vault_path=vault_root, path=normalized)
        return _vault_path_operation_response(
            operation=operation,
            path=normalized,
            kind="directory",
            result=result,
        )

    if not full_path.exists():
        raise APIException(
            status_code=404,
            error_type="VaultPathNotFound",
            message=f"Vault path not found: {normalized}",
            details={"path": normalized, "vault_name": vault_name},
        )

    if operation == "move":
        normalized_destination = _normalize_vault_file_path(destination)
        kind: Literal["file", "directory"] = (
            "directory" if full_path.is_dir() else "file"
        )
        if kind == "directory":
            result = move_vault_directory_operation(
                vault_path=vault_root,
                path=normalized,
                destination=normalized_destination,
            )
        else:
            result = move_vault_path_operation(
                vault_path=vault_root,
                path=normalized,
                destination=normalized_destination,
                overwrite=False,
            )
        return _vault_path_operation_response(
            operation=operation,
            path=normalized,
            destination=normalized_destination,
            kind=kind,
            result=result,
        )

    if operation == "delete":
        kind = "directory" if full_path.is_dir() else "file"
        if kind == "directory" and any(full_path.iterdir()):
            raise APIException(
                status_code=409,
                error_type="VaultDirectoryNotEmpty",
                message=f"Cannot delete non-empty directory: {normalized}",
                details={"path": normalized, "vault_name": vault_name},
            )
        result = delete_vault_path_operation(
            vault_path=vault_root,
            path=normalized,
            confirm_path=normalized,
        )
        return _vault_path_operation_response(
            operation=operation,
            path=normalized,
            kind=kind,
            result=result,
        )

    raise APIException(
        status_code=400,
        error_type="InvalidVaultPathMutation",
        message=f"Unsupported vault path mutation: {operation}",
        details={"operation": operation, "path": normalized},
    )


@contextmanager
def _explorer_activity(
    *,
    label: str,
) -> Iterator[VaultActivityContext]:
    """Track one synchronous Explorer command as durable vault activity."""
    context = VaultActivityContext(
        activity_id=f"activity_{uuid.uuid4().hex}",
        kind="explorer",
        source="api",
        scope=None,
        label=label,
    )
    service = VaultStateService()
    with use_vault_activity(context):
        try:
            yield context
        except Exception:
            service.finish_activity(activity_id=context.activity_id, status="failed")
            raise
        else:
            service.finish_activity(activity_id=context.activity_id, status="completed")


def _vault_path_operation_response(
    *,
    operation: str,
    path: str,
    kind: Literal["file", "directory"],
    result: VaultFileOperationResult,
    destination: str = "",
) -> VaultPathMutationResponse:
    status = str(result.metadata.get("status") or "error")
    if status != "completed":
        status_code = (
            404 if status == "not_found" else 409 if status == "already_exists" else 400
        )
        raise APIException(
            status_code=status_code,
            error_type=str(
                result.metadata.get("error_type") or "VaultPathMutationFailed"
            ),
            message=str(result.return_value),
            details={"path": path, "destination": destination, **result.metadata},
        )
    return VaultPathMutationResponse(
        operation=operation,
        path=path,
        destination=destination,
        kind=kind,
        message=str(result.return_value),
        metadata=dict(result.metadata),
    )


def _vault_path_mutation_error(
    exc: VaultMutationRejected,
    *,
    vault_name: str,
    path: str,
) -> APIException:
    status_by_code = {
        "file_exists": 409,
        "file_not_found": 404,
        "invalid_path": 400,
    }
    return APIException(
        status_code=status_by_code.get(exc.code, 400),
        error_type=exc.code,
        message=str(exc),
        details={"path": path, "vault_name": vault_name},
    )


def _normalize_chat_reference_candidate(path: str) -> str:
    raw_path = str(path or "").strip().removeprefix("@").replace("\\", "/")
    if len(raw_path) > 1000:
        raise APIException(
            status_code=400,
            error_type="InvalidVaultReferencePath",
            message="Vault reference path is too long.",
            details={"path": raw_path[:100]},
        )
    if raw_path.startswith("/") or ".." in raw_path.split("/"):
        raise APIException(
            status_code=400,
            error_type="InvalidVaultReferencePath",
            message="Vault reference paths must stay relative to the vault.",
            details={"path": raw_path},
        )
    return normalize_vault_relative_path(raw_path)


def _resolved_chat_path_item(
    *,
    vault_root: Path,
    requested_path: str,
    candidate: Path,
    source: Literal["workspace", "vault"],
) -> VaultPathResolutionInfo | None:
    if not candidate.exists() or not (candidate.is_file() or candidate.is_dir()):
        return None
    try:
        relative = candidate.resolve().relative_to(vault_root).as_posix()
    except ValueError:
        return None
    if any(part.startswith(".") for part in Path(relative).parts):
        return None
    return VaultPathResolutionInfo(
        requested_path=requested_path,
        path=relative,
        kind="directory" if candidate.is_dir() else "file",
        source=source,
    )


def _list_vault_file_reference_children(
    *,
    vault_root: Path,
    base_dir: Path,
    workspace_path: str,
    limit: int,
    offset: int = 0,
) -> tuple[list[VaultFileReferenceInfo], bool]:
    items: list[VaultFileReferenceInfo] = []
    eligible_index = 0
    truncated = False
    for child in sorted(
        base_dir.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
    ):
        if not _is_file_reference_path(child):
            continue
        if eligible_index < offset:
            eligible_index += 1
            continue
        if len(items) >= limit:
            truncated = True
            break
        info = _vault_file_reference_info(
            vault_root=vault_root,
            path=child,
            workspace_path=workspace_path,
        )
        if info is not None:
            items.append(info)
        eligible_index += 1
    return items, truncated


def _search_vault_file_references(
    *,
    vault_root: Path,
    base_dir: Path,
    workspace_path: str,
    query: str,
    limit: int,
) -> tuple[list[VaultFileReferenceInfo], bool]:
    matches: list[VaultFileReferenceInfo] = []
    for child in base_dir.rglob("*"):
        if len(matches) > limit:
            break
        if not _is_file_reference_path(child):
            continue
        try:
            relative = child.resolve().relative_to(vault_root).as_posix()
        except ValueError:
            continue
        haystack = f"{child.name.lower()} {relative.lower()}"
        if query not in haystack:
            continue
        info = _vault_file_reference_info(
            vault_root=vault_root,
            path=child,
            workspace_path=workspace_path,
        )
        if info is not None:
            matches.append(info)
    ordered = sorted(
        matches,
        key=lambda item: (
            not item.in_workspace,
            item.kind != "directory",
            item.path.lower(),
        ),
    )
    return ordered[:limit], len(ordered) > limit


def _is_file_reference_path(path: Path) -> bool:
    """Return whether a filesystem path should be shown in the reference picker."""
    return not any(part.startswith(".") for part in path.parts)


def _vault_file_reference_info(
    *,
    vault_root: Path,
    path: Path,
    workspace_path: str,
) -> VaultFileReferenceInfo | None:
    try:
        relative = path.resolve().relative_to(vault_root).as_posix()
    except ValueError:
        return None
    is_directory = path.is_dir()
    try:
        stat_result = path.stat()
    except OSError:
        stat_result = None
    workspace_prefix = f"{workspace_path.rstrip('/')}/" if workspace_path else ""
    in_workspace = (
        not workspace_path
        or relative == workspace_path
        or relative.startswith(workspace_prefix)
    )
    has_children = False
    if is_directory:
        try:
            has_children = any(
                _is_file_reference_path(child) for child in path.iterdir()
            )
        except OSError:
            has_children = False
    return VaultFileReferenceInfo(
        name=path.name or relative,
        path=relative,
        kind="directory" if is_directory else "file",
        size_bytes=None if is_directory or stat_result is None else stat_result.st_size,
        modified_at=(
            None
            if stat_result is None
            else datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)
        ),
        has_children=has_children,
        in_workspace=in_workspace,
    )


def set_chat_session_workspace(
    vault_name: str, session_id: str, path: str | None
) -> ChatWorkspaceInfo | None:
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


def set_chat_session_mode(
    vault_name: str, session_id: str, chat_mode: str
) -> Literal["normal", "inline_edit"]:
    """Set the selected mode for an existing chat session."""
    existing_session = _chat_store.get_session_by_id(session_id)
    if existing_session is None:
        raise APIException(
            status_code=404,
            error_type="ChatSessionNotFound",
            message=f"Chat session not found: {session_id}",
        )
    if existing_session.vault_name != vault_name:
        raise APIException(
            status_code=409,
            error_type="ChatSessionVaultMismatch",
            message=f"Chat session '{session_id}' belongs to another vault.",
        )
    normalized: Literal["normal", "inline_edit"] = (
        "inline_edit" if str(chat_mode).strip().lower() == "inline_edit" else "normal"
    )
    _chat_store.set_session_chat_mode(
        session_id=session_id,
        vault_name=vault_name,
        chat_mode=normalized,
    )
    return normalized


def get_system_database_migration_status() -> SystemMigrationStatusResponse:
    """Return registered system database migration status."""
    try:
        status = get_registered_system_migration_status(get_system_root())
    except Exception as exc:
        raise SystemConfigurationError(
            f"Failed to inspect system database migrations: {exc}"
        ) from exc

    return _build_system_migration_status_response(status)


def run_system_database_migrations(backup: bool = True) -> SystemMigrationRunResponse:
    """Run registered system database migrations on demand."""
    try:
        status = run_registered_system_migrations(get_system_root(), backup=backup)
    except Exception as exc:
        raise SystemConfigurationError(
            f"Failed to run system database migrations: {exc}"
        ) from exc

    backups_created = [
        target.backup_path for target in status.targets if target.backup_path
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
        raise SystemConfigurationError(
            f"Failed to refresh system authoring templates: {exc}"
        ) from exc

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
) -> list[APIConfigurationError]:
    """Return workflow configuration errors, optionally filtered by vault/workflow."""
    errors = get_configuration_errors()
    if vault_name:
        errors = [error for error in errors if error.vault == vault_name]
    if workflow_name:
        errors = [error for error in errors if error.workflow_name == workflow_name]
    return errors


def set_system_startup_time(startup_time: datetime):
    """Set the system startup time for status reporting."""
    global _system_startup_time
    _system_startup_time = startup_time


def list_context_templates(vault_name: str) -> list[TemplateInfo]:
    """List available context templates for a given vault."""
    vault_path: str | None = None
    try:
        vault_path = _get_vault_path(vault_name)
    except Exception as exc:
        logger.warning(
            f"Vault path lookup failed for '{vault_name}', falling back to system templates only: {exc}"
        )

    templates = list_templates(Path(vault_path) if vault_path else None)
    results: list[TemplateInfo] = []
    for tmpl in templates:
        results.append(
            TemplateInfo(
                name=tmpl.name,
                source=tmpl.source,
                path=str(tmpl.path) if tmpl.path else None,
            )
        )
    return results


def list_chat_sessions(vault_name: str) -> list[ChatSessionInfo]:
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
            chat_mode=_chat_store.get_session_chat_mode(session.session_id, vault_name),
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

    source_messages = _chat_store.get_stored_messages(source_session_id, vault_name)
    highest_sequence = max(
        (message.sequence_index for message in source_messages), default=-1
    )
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
                f"effective message sequence {highest_sequence}."
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
    new_session = _chat_store.get_session(
        session_id=new_session_id, vault_name=vault_name
    )
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
            "workspace_path": _chat_store.get_session_workspace_path(
                new_session_id, vault_name
            )
            or None,
        },
    )
    return ChatSessionForkResponse(
        session=ChatSessionInfo(
            session_id=new_session.session_id,
            created_at=new_session.created_at,
            last_activity_at=new_session.last_activity_at,
            title=new_session.title or None,
            workspace=_chat_workspace_info(
                _chat_store.get_session_workspace_path(
                    new_session.session_id, vault_name
                )
            ),
            chat_mode=_chat_store.get_session_chat_mode(
                new_session.session_id, vault_name
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
            "workspace_path": _chat_store.get_session_workspace_path(
                session_id, vault_name
            )
            or None,
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


def get_chat_session_detail(
    vault_name: str, session_id: str
) -> ChatSessionDetailResponse:
    """Return persisted chat messages for one session."""
    messages = _chat_store.get_stored_messages(session_id, vault_name)
    tool_events = _chat_store.get_tool_events(
        session_id, vault_name, committed_only=True
    )
    metadata = _chat_store.get_session_metadata(session_id, vault_name)
    latest_failure = _chat_session_failure_info(metadata.get("latest_turn_failure"))
    pending_review = get_pending_deferred_review(
        vault_name=vault_name, session_id=session_id
    )
    return ChatSessionDetailResponse(
        session_id=session_id,
        vault_name=vault_name,
        workspace=_chat_workspace_info(
            _chat_store.get_session_workspace_path(session_id, vault_name)
        ),
        chat_mode=_chat_store.get_session_chat_mode(session_id, vault_name),
        pending_review=(
            _deferred_review_response(pending_review)
            if pending_review is not None
            else None
        ),
        latest_failure=latest_failure,
        messages=[
            ChatSessionMessageInfo(
                sequence_index=message.sequence_index,
                fork_sequence_index=message.fork_sequence_index,
                role=message.role,
                content=_chat_message_display_content(message),
                thinking_content=_chat_message_thinking_content(message),
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


def _chat_message_display_content(message) -> str:
    """Return chat content for UI rendering without changing stored search text."""
    if not isinstance(message.message, ModelResponse):
        return message.content_text

    text_parts: list[str] = []
    for part in getattr(message.message, "parts", []) or []:
        if isinstance(part, TextPart) and isinstance(part.content, str):
            content = part.content.strip()
            if content:
                text_parts.append(content)

    if not text_parts:
        return message.content_text

    return "\n\n".join(text_parts)


def _chat_message_thinking_content(message) -> str:
    """Return persisted provider thinking content separately from answer markdown."""
    if not isinstance(message.message, ModelResponse):
        return ""

    thinking_parts: list[str] = []
    for part in getattr(message.message, "parts", []) or []:
        if isinstance(part, ThinkingPart) and isinstance(part.content, str):
            content = part.content.strip()
            if content:
                thinking_parts.append(content)

    if not thinking_parts:
        return ""

    return _format_thinking_display_text("\n\n".join(thinking_parts))


def _format_thinking_display_text(text: str) -> str:
    """Light display cleanup for providers that stream sentence chunks without spaces."""
    return re.sub(r"""([.!?]["')\]]?)(?=[A-Z])""", r"\1 ", text)


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
            failure_kind=str(value.get("failure_kind") or ""),
            retryable=bool(value.get("retryable", False)),
            http_status=(
                None
                if value.get("http_status") is None
                else int(value.get("http_status"))
            ),
            retry_after=(
                None
                if value.get("retry_after") is None
                else str(value.get("retry_after"))
            ),
            model=None if value.get("model") is None else str(value.get("model")),
            tools=[str(item) for item in value.get("tools") or ()],
            accepted_user_sequence_index=int(value.get("accepted_user_sequence_index")),
            recorded_at=str(value.get("recorded_at") or ""),
            suggested_action=str(value.get("suggested_action") or ""),
            manual_retry_count=max(int(value.get("manual_retry_count") or 0), 0),
            last_manual_retry_task_id=(
                None
                if value.get("last_manual_retry_task_id") is None
                else str(value.get("last_manual_retry_task_id"))
            ),
            last_manual_retry_started_at=(
                None
                if value.get("last_manual_retry_started_at") is None
                else str(value.get("last_manual_retry_started_at"))
            ),
        )
    except (TypeError, ValueError):
        return None


def set_chat_session_title(vault_name: str, session_id: str, title: str | None) -> None:
    """Set or clear the user-defined title for a chat session."""
    _chat_store.set_session_title(session_id, vault_name, title)


def export_chat_session_markdown(
    vault_name: str, vault_path: str, session_id: str
) -> ChatSessionExportResponse:
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
    result = await runtime.task_runner.run_inline(
        ExecutionTaskSpec(
            kind=ExecutionTaskKind.HISTORY_COMPACTION,
            scope=chat_session_scope(session_id),
            source=ExecutionTaskSource.API,
            label=compaction_task_label(session_id),
            metadata={"vault": vault_name, "session_id": session_id},
        ),
        lambda _task: compact_chat_history(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
            focus=focus,
            source=ExecutionTaskSource.API,
            store=_chat_store,
        ),
    )
    return ChatHistoryCompactionResponse(**result.as_api_dict())


def delete_chat_session(vault_name: str, vault_path: str, session_id: str) -> None:
    """Delete one chat session and its session summary."""
    del vault_path
    _chat_store.delete_sessions(vault_name, session_id=session_id)
    SessionSummaryStore().delete_session_summary(
        vault_name=vault_name, session_id=session_id
    )


def purge_chat_sessions(
    vault_name: str,
    vault_path: str,
    *,
    older_than_days: int | None,
) -> ChatSessionsPurgeResponse:
    """Delete old chat sessions and their transcript files for a vault."""
    deleted_ids = _chat_store.delete_sessions(
        vault_name, older_than_days=older_than_days
    )
    summary_store = SessionSummaryStore()
    for session_id in deleted_ids:
        summary_store.delete_session_summary(
            vault_name=vault_name, session_id=session_id
        )
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


def _load_json_object(raw_value: str | None) -> dict[str, Any] | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return {"raw": raw_value}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


async def collect_vault_status() -> list[VaultInfo]:
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
                path=data["path"],
                workflow_count=len(data["workflows"]),
                workflows=data["workflows"],
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


def _collect_vault_state_summary() -> dict[str, dict[str, Any]]:
    """Return cheap vault-state summary fields keyed by current vault name."""
    summary: dict[str, dict[str, Any]] = {}
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
                select(
                    VaultFileEvent.vault_name, func.max(VaultFileEvent.observed_at)
                ).group_by(VaultFileEvent.vault_name)
            ).all()
            for vault_name, latest_change in change_rows:
                summary.setdefault(vault_name, {})[
                    "latest_vault_change_at"
                ] = latest_change

            recent_change_rows = session.execute(
                select(
                    VaultFileEvent.vault_name, VaultFileEvent.event_type, func.count()
                )
                .where(
                    VaultFileEvent.observed_at >= recent_change_cutoff,
                    VaultFileEvent.event_type.in_(("created", "deleted")),
                )
                .group_by(VaultFileEvent.vault_name, VaultFileEvent.event_type)
            ).all()
            for vault_name, event_type, count in recent_change_rows:
                key = (
                    "files_created_recent"
                    if event_type == "created"
                    else "files_deleted_recent"
                )
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
        runtime = None
        try:
            runtime = get_runtime_context()
        except RuntimeStateError:
            runtime = None

        # If no scheduler provided, get from runtime context
        if scheduler is None:
            if runtime is not None:
                scheduler = runtime.scheduler

        if scheduler is None:
            # Return default scheduler info if unavailable
            return SchedulerInfo(
                running=False, total_jobs=0, enabled_workflows=0, disabled_workflows=0
            )

        # Get scheduler status
        is_running = scheduler.running

        # Get detailed job information using APScheduler's get_jobs()
        jobs = scheduler.get_jobs()
        total_jobs = len(jobs)

        # Extract job details from APScheduler
        job_summaries = []
        for job in jobs:
            job_type = "system" if job.id in SYSTEM_JOB_IDS else "workflow"
            history = get_scheduler_job_history(job.id) or {}
            if job_type == "workflow" and runtime is not None:
                workflow_id = job.id.replace("__", "/")
                latest_run = runtime.workflow_run_store.get_latest_run(workflow_id)
                if latest_run is not None:
                    unhealthy = latest_run.status in {"failed", "timed_out", "missed"}
                    history = {
                        "last_run_time": latest_run.completed_at,
                        "last_status": latest_run.status,
                        "last_error": latest_run.reason if unhealthy else None,
                        "last_run_id": latest_run.run_id,
                        "last_run_source": latest_run.source,
                    }
            job_summary = {
                "id": job.id,
                "name": job.name,
                "job_type": job_type,
                "next_run_time": job.next_run_time,
                "last_run_time": history.get("last_run_time"),
                "last_status": history.get("last_status"),
                "last_error": history.get("last_error"),
                "last_run_id": history.get("last_run_id"),
                "last_run_source": history.get("last_run_source"),
                "trigger_type": type(job.trigger).__name__,
                "trigger_description": str(job.trigger),
                "max_instances": job.max_instances,
                "misfire_grace_time": job.misfire_grace_time,
            }
            job_summaries.append(job_summary)

        # Sort by next run time for better display
        job_summaries.sort(key=lambda x: x["next_run_time"] or datetime.max)

        # Remove redundant workflow counting - this will be done at the higher level using cached data
        scheduler_info = SchedulerInfo(
            running=is_running,
            total_jobs=total_jobs,
            enabled_workflows=0,  # Will be calculated elsewhere
            disabled_workflows=0,  # Will be calculated elsewhere
            job_details=job_summaries,  # Add rich job data
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
            job_details=[],
        )


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
            data_root=data_root,
        )

        return system_info

    except Exception:
        # Return safe defaults on error
        return SystemInfo(startup_time=datetime.now(), data_root="/app/data")


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
        enabled_workflows = [
            summary for summary in workflow_summaries if summary.enabled
        ]
        disabled_workflows = [
            summary for summary in workflow_summaries if not summary.enabled
        ]
        system_workflow_templates = get_system_workflow_template_summaries()
        runtime = get_runtime_context()
        latest_workflow_runs = _project_latest_workflow_runs(
            workflow_summaries=workflow_summaries,
            system_workflow_templates=system_workflow_templates,
            latest_runs=runtime.workflow_run_store.list_latest_runs(),
        )

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
            workflow_runs=latest_workflow_runs,
            configuration_errors=configuration_errors,
            configuration_status=configuration_status,
        )

        return status_response

    except Exception as e:
        error_msg = f"Failed to collect system status: {str(e)}"
        raise SystemConfigurationError(error_msg) from e


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


async def rescan_vaults_and_update_scheduler(scheduler=None) -> dict[str, Any]:
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


async def get_system_activity_log(
    *,
    limit: int = 200,
    cursor: str | None = None,
    levels: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    search: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> SystemLogResponse:
    """Return one filtered newest-first page from retained System Activity."""
    log_path = get_system_root() / "activity.log"

    try:
        page = query_activity_log(
            log_path,
            limit=limit,
            cursor=cursor,
            levels=levels,
            tags=tags,
            search=search,
            start_time=start_time,
            end_time=end_time,
        )
    except ValueError as exc:
        raise APIException(
            status_code=400,
            error_type="InvalidActivityCursor",
            message=str(exc),
        ) from exc
    except OSError as exc:
        raise SystemConfigurationError(f"Failed to query activity log: {exc}") from exc

    if not page.entries:
        return SystemLogResponse(
            entries=[],
            next_cursor=None,
            earliest_retained_timestamp=page.earliest_retained_timestamp,
            total_matching=page.total_matching,
            retained_size_bytes=page.total_size_bytes,
            available_levels=page.available_levels,
            available_tags=page.available_tags,
        )

    return SystemLogResponse(
        entries=page.entries,
        next_cursor=page.next_cursor,
        earliest_retained_timestamp=page.earliest_retained_timestamp,
        total_matching=page.total_matching,
        retained_size_bytes=page.total_size_bytes,
        available_levels=page.available_levels,
        available_tags=page.available_tags,
    )


def export_system_activity_log():
    """Yield retained raw System Activity JSONL in chronological order."""
    return iter_activity_export(get_system_root() / "activity.log")


def _build_settings_response(path: Path) -> SystemSettingsResponse:
    content = path.read_text(encoding="utf-8")
    return SystemSettingsResponse(
        path=str(path), content=content, size_bytes=len(content.encode("utf-8"))
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
        raise SystemConfigurationError(
            "Settings YAML must contain a top-level mapping (dictionary)."
        )

    normalized_content = (
        new_content if new_content.endswith("\n") else new_content + "\n"
    )

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
        template_raw = (
            yaml.safe_load(SETTINGS_TEMPLATE.read_text(encoding="utf-8")) or {}
        )
    except FileNotFoundError as exc:
        raise SystemConfigurationError("Template settings file not found.") from exc
    except yaml.YAMLError as exc:
        raise SystemConfigurationError(
            f"Failed to read template settings: {exc}"
        ) from exc

    try:
        active_raw = yaml.safe_load(active_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SystemConfigurationError(
            f"Failed to read active settings: {exc}"
        ) from exc

    if not isinstance(active_raw, dict):
        raise SystemConfigurationError("Active settings file is not a valid mapping.")
    if not isinstance(template_raw, dict):
        raise SystemConfigurationError("Template settings file is not a valid mapping.")

    # Apply centralized contract upgrades before merging template defaults.
    merged = upgrade_settings_mapping(active_raw, template_raw)
    for section in ("settings", "models", "providers", "tools"):
        if merged.get(section) is None or not isinstance(merged.get(section), dict):
            merged[section] = {}

    template_sections: dict[str, dict] = {}
    for section in ("settings", "models", "providers", "tools"):
        section_val = template_raw.get(section)
        template_sections[section] = (
            section_val if isinstance(section_val, dict) else {}
        )

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

    # Existing settings entries may need newly introduced metadata fields
    # from the template. Preserve active values and only fill absent metadata.
    active_settings = merged.get("settings", {})
    template_settings = template_sections.get("settings", {})
    if isinstance(active_settings, dict) and isinstance(template_settings, dict):
        for key, template_setting in template_settings.items():
            active_setting = active_settings.get(key)
            if isinstance(active_setting, dict) and isinstance(template_setting, dict):
                for metadata_key in ("description", "category", "restart_required"):
                    if metadata_key in template_setting:
                        active_setting.setdefault(
                            metadata_key, template_setting[metadata_key]
                        )

    # Existing core provider entries may need newly introduced non-secret fields
    # from the template. Preserve all active values and only fill absent keys.
    active_providers = merged.get("providers", {})
    template_providers = template_sections.get("providers", {})
    if isinstance(active_providers, dict) and isinstance(template_providers, dict):
        for key, template_provider in template_providers.items():
            active_provider = active_providers.get(key)
            if isinstance(active_provider, dict) and isinstance(
                template_provider, dict
            ):
                for provider_key, provider_value in template_provider.items():
                    active_provider.setdefault(provider_key, provider_value)

    # Prune removed settings (settings are not user-extensible)
    settings_template_keys = set(template_sections["settings"].keys())
    merged["settings"] = {
        key: val
        for key, val in merged["settings"].items()
        if key in settings_template_keys
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
        raise SystemConfigurationError(
            f"Failed to create settings backup: {exc}"
        ) from exc

    try:
        active_path.write_text(
            yaml.safe_dump(merged, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
    except Exception as exc:
        raise SystemConfigurationError(
            f"Failed to write repaired settings: {exc}"
        ) from exc

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
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | dict):
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
        category=getattr(entry, "category", None),
        restart_required=bool(getattr(entry, "restart_required", False)),
    )


def get_general_settings_config() -> list[SettingInfo]:
    """Return serialized general settings metadata."""
    settings_map = list_general_settings()
    return [_build_setting_info(key, entry) for key, entry in settings_map.items()]


def update_general_setting_value(
    setting_name: str, payload: SettingUpdateRequest
) -> SettingInfo:
    """Persist a general setting update and refresh configuration caches."""
    try:
        updated = update_general_setting(setting_name, payload.value)
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration(restart_required=updated.restart_required)
    setting_info = _build_setting_info(setting_name, updated)
    setting_info.restart_required = (
        setting_info.restart_required or reload_result.restart_required
    )
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
    availability: dict[str, bool],
    issue_messages: dict[str, str] | None = None,
) -> ModelInfo:
    if hasattr(config, "provider"):
        provider = config.provider
        model_string = config.model_string
        capabilities = list(getattr(config, "capabilities", ["text"]) or ["text"])
        dimensions = getattr(config, "dimensions", None)
        user_editable = getattr(config, "user_editable", True)
        description = getattr(config, "description", None)
    else:
        provider = config["provider"]
        model_string = config["model_string"]
        capabilities = list(config.get("capabilities", ["text"]) or ["text"])
        dimensions = config.get("dimensions")
        user_editable = config.get("user_editable", True)
        description = config.get("description")

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


def _general_setting_value(name: str, default: Any) -> Any:
    entry = list_general_settings().get(name)
    return getattr(entry, "value", default) if entry is not None else default


def _editable_builtin_providers() -> set[str]:
    value = _general_setting_value("editable_builtin_providers", [])
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def _openai_oauth_enabled() -> bool:
    return openai_oauth_enabled_from_settings(list_general_settings())


def _build_provider_info(
    name: str, config, restart_required: bool = False
) -> ProviderInfo:
    if hasattr(config, "api_key"):
        raw_api_key = config.api_key
        raw_base_url = getattr(config, "base_url", None)
        stored_user_editable = getattr(config, "user_editable", False)
        fallback_enabled = bool(
            getattr(config, "oauth_api_key_fallback_enabled", False)
        )
    else:
        raw_api_key = config.get("api_key")
        raw_base_url = config.get("base_url")
        stored_user_editable = config.get("user_editable", False)
        fallback_enabled = bool(config.get("oauth_api_key_fallback_enabled", False))

    api_key_env = raw_api_key if raw_api_key else None
    base_url_env = raw_base_url if raw_base_url else None
    user_editable = bool(stored_user_editable) or name in _editable_builtin_providers()

    api_key_has_value = openai_provider_api_key_available(
        config,
        secret_has_value=secret_has_value,
    )
    base_url_has_value = openai_provider_base_url_available(
        config,
        get_secret_value=get_secret_value,
    )

    provider_info = ProviderInfo(
        name=name,
        api_key=api_key_env,
        base_url=base_url_env,
        user_editable=user_editable,
        api_key_has_value=api_key_has_value,
        base_url_has_value=base_url_has_value,
        restart_required=restart_required,
    )

    if name != "openai":
        return provider_info

    oauth_enabled = _openai_oauth_enabled()
    oauth_connection = get_openai_oauth_status()
    resolution = resolve_openai_auth(
        config,
        oauth_enabled=oauth_enabled,
        oauth_connected=oauth_connection.connected,
        api_key_available=api_key_has_value,
        base_url_available=base_url_has_value,
        emit_log=False,
    )
    configured_auth_mode = resolution.configured_auth_mode
    effective_auth_mode = resolution.effective_auth_mode
    oauth_status = "disabled" if not oauth_enabled else oauth_connection.status
    oauth_disabled_reason = "global_setting" if not oauth_enabled else None

    provider_info.configured_auth_mode = configured_auth_mode
    provider_info.effective_auth_mode = effective_auth_mode
    provider_info.oauth_enabled = oauth_enabled
    provider_info.oauth_status = oauth_status
    provider_info.oauth_disabled_reason = oauth_disabled_reason
    provider_info.oauth_api_key_fallback_enabled = fallback_enabled
    provider_info.oauth_api_key_fallback_available = resolution.fallback_available
    provider_info.oauth_account_id = oauth_connection.account_id
    provider_info.oauth_expires_at = oauth_connection.expires_at
    provider_info.oauth_last_refresh_at = oauth_connection.last_refresh_at
    provider_info.oauth_last_refresh_error = oauth_connection.last_refresh_error
    provider_info.oauth_pending_expires_at = oauth_connection.pending_expires_at
    provider_info.oauth_pending_flow = oauth_connection.pending_flow
    provider_info.oauth_device_verification_url = (
        oauth_connection.device_verification_url
    )
    provider_info.oauth_device_user_code = oauth_connection.device_user_code
    provider_info.oauth_device_poll_interval_seconds = (
        oauth_connection.device_poll_interval_seconds
    )
    return provider_info


def _derive_secret_name(provider_name: str, suffix: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", provider_name).upper().strip("_")
    if not slug:
        slug = "PROVIDER"
    clean_suffix = suffix.upper().lstrip("_")
    return f"{slug}_{clean_suffix}" if clean_suffix else slug


def _normalize_secret_pointer(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", trimmed).upper().strip("_")
    if not normalized:
        raise SystemConfigurationError("Secret names must include letters or numbers.")
    return normalized


def get_configurable_models() -> list[ModelInfo]:
    """Return model configuration entries with availability metadata."""
    config_status = validate_settings()
    models_config = get_models_config()
    issue_messages = {
        issue.name.split(":", 1)[1]: issue.message
        for issue in config_status.issues
        if issue.name.startswith("model:")
    }
    return [
        _build_model_info(
            name, config, config_status.model_availability, issue_messages
        )
        for name, config in models_config.items()
    ]


def upsert_configurable_model(
    model_name: str, payload: ModelConfigRequest
) -> ModelInfo:
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
        issue.name.split(":", 1)[1]: issue.message
        for issue in config_status.issues
        if issue.name.startswith("model:")
    }

    logger.info(
        "Model alias upserted",
        data={"alias": model_name, "provider": payload.provider},
    )
    return _build_model_info(
        model_name, updated, config_status.model_availability, issue_messages
    )


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


def get_configurable_providers() -> list[ProviderInfo]:
    """Return provider configurations suitable for user editing."""
    providers_config = get_providers_config()
    return [
        _build_provider_info(name, config) for name, config in providers_config.items()
    ]


def _openai_provider_info(restart_required: bool = False) -> ProviderInfo:
    providers_config = get_providers_config()
    config = providers_config.get("openai")
    if config is None:
        raise SystemConfigurationError("Built-in openai provider is not configured.")
    return _build_provider_info("openai", config, restart_required=restart_required)


def start_openai_oauth_connection(
    payload: OpenAIOAuthStartRequest,
    *,
    default_redirect_uri: str,
) -> OpenAIOAuthStartResponse:
    """Start an OpenAI OAuth connection attempt."""

    if not _openai_oauth_enabled():
        raise SystemConfigurationError("OpenAI OAuth is disabled by global setting.")
    redirect_uri = payload.redirect_uri or default_redirect_uri
    try:
        result = start_openai_oauth_attempt(redirect_uri=redirect_uri)
    except OpenAIOAuthStateError as exc:
        raise SystemConfigurationError(str(exc)) from exc
    logger.info(
        "OpenAI OAuth start created",
        data={"redirect_uri_configured": bool(payload.redirect_uri)},
    )
    return OpenAIOAuthStartResponse(
        auth_url=result.auth_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
        expires_at=result.expires_at,
    )


async def start_openai_oauth_device_connection() -> OpenAIOAuthDeviceStartResponse:
    """Start an OpenAI OAuth device-code connection attempt."""

    if not _openai_oauth_enabled():
        raise SystemConfigurationError("OpenAI OAuth is disabled by global setting.")
    try:
        result = await start_openai_oauth_device_code()
    except OpenAIOAuthStateError as exc:
        raise SystemConfigurationError(str(exc)) from exc
    logger.info(
        "OpenAI OAuth device-code start created",
        data={"poll_interval_seconds": result.poll_interval_seconds},
    )
    return OpenAIOAuthDeviceStartResponse(
        verification_url=result.verification_url,
        user_code=result.user_code,
        expires_at=result.expires_at,
        poll_interval_seconds=result.poll_interval_seconds,
    )


async def check_openai_oauth_device_connection() -> OpenAIOAuthDeviceCheckResponse:
    """Check an OpenAI OAuth device-code connection attempt."""

    if not _openai_oauth_enabled():
        raise SystemConfigurationError("OpenAI OAuth is disabled by global setting.")
    try:
        token_state = await poll_openai_oauth_device_code()
    except OpenAIOAuthStateError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    status = "connected" if token_state is not None else "pending"
    logger.info("OpenAI OAuth device-code checked", data={"status": status})
    return OpenAIOAuthDeviceCheckResponse(
        status=status,
        provider=_openai_provider_info(),
    )


async def complete_openai_oauth_callback(code: str, state: str) -> ProviderInfo:
    """Complete OpenAI OAuth from callback query parameters."""

    if not _openai_oauth_enabled():
        raise SystemConfigurationError("OpenAI OAuth is disabled by global setting.")
    try:
        await complete_openai_oauth(code=code, state=state)
    except OpenAIOAuthStateError as exc:
        raise SystemConfigurationError(str(exc)) from exc
    logger.info("OpenAI OAuth callback completed", data={"manual": False})
    return _openai_provider_info()


async def complete_openai_oauth_manual(
    payload: OpenAIOAuthCompleteRequest,
) -> ProviderInfo:
    """Complete OpenAI OAuth from a pasted redirect URL or code/state pair."""

    if not _openai_oauth_enabled():
        raise SystemConfigurationError("OpenAI OAuth is disabled by global setting.")
    try:
        await complete_openai_oauth_from_redirect(
            redirect_url=payload.redirect_url,
            code=payload.code,
            state=payload.state,
        )
    except OpenAIOAuthStateError as exc:
        raise SystemConfigurationError(str(exc)) from exc
    logger.info("OpenAI OAuth manual completion finished", data={"manual": True})
    return _openai_provider_info()


def disconnect_openai_oauth_connection() -> OperationResult:
    """Clear OpenAI OAuth token and pending state without changing provider mode."""

    clear_openai_oauth_state()
    logger.info("OpenAI OAuth disconnected", data={})
    return OperationResult(success=True, message="OpenAI OAuth connection cleared.")


def upsert_configurable_provider(
    provider_name: str, payload: ProviderConfigRequest
) -> ProviderInfo:
    """Create or update a provider configuration entry."""
    providers_config = get_providers_config()
    existing_config = providers_config.get(provider_name)

    # Only reference existing secret names; actual secret values are managed via the Secrets form.
    existing_api_key = None
    existing_base_url = None
    existing_auth_mode = "api_key"
    existing_fallback_enabled = False
    if existing_config:
        if hasattr(existing_config, "api_key"):
            existing_api_key = existing_config.api_key
            existing_base_url = getattr(existing_config, "base_url", None)
            existing_auth_mode = getattr(existing_config, "auth_mode", "api_key")
            existing_fallback_enabled = bool(
                getattr(existing_config, "oauth_api_key_fallback_enabled", False)
            )
        else:
            existing_api_key = existing_config.get("api_key")
            existing_base_url = existing_config.get("base_url")
            existing_auth_mode = existing_config.get("auth_mode", "api_key")
            existing_fallback_enabled = bool(
                existing_config.get("oauth_api_key_fallback_enabled", False)
            )

    fields_set = getattr(payload, "model_fields_set", set())
    openai_auth_fields = {"auth_mode", "oauth_api_key_fallback_enabled"}
    if provider_name != "openai" and fields_set.intersection(openai_auth_fields):
        raise SystemConfigurationError(
            "OpenAI auth metadata can only be configured for the built-in openai provider."
        )

    if "api_key" in fields_set:
        api_key = _normalize_secret_pointer(payload.api_key)
    else:
        api_key = existing_api_key

    if "base_url" in fields_set:
        base_url = _normalize_secret_pointer(payload.base_url)
    else:
        base_url = existing_base_url

    if "auth_mode" in fields_set:
        auth_mode = payload.auth_mode
    else:
        auth_mode = existing_auth_mode

    if "oauth_api_key_fallback_enabled" in fields_set:
        fallback_enabled = bool(payload.oauth_api_key_fallback_enabled)
    else:
        fallback_enabled = existing_fallback_enabled

    try:
        updated = upsert_provider_config(
            name=provider_name,
            api_key=api_key,
            base_url=base_url,
            auth_mode=auth_mode,
            oauth_api_key_fallback_enabled=fallback_enabled,
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
            "auth_mode": auth_mode if provider_name == "openai" else None,
            "oauth_api_key_fallback_enabled": (
                fallback_enabled if provider_name == "openai" else None
            ),
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


def list_secrets() -> list[SecretInfo]:
    entries = list_secret_entries()
    recorded_entries = {
        entry.name: entry
        for entry in entries
        if not is_openai_oauth_internal_secret(entry.name)
    }
    ordered_names: list[str] = [
        entry.name for entry in entries if entry.name in recorded_entries
    ]

    known_names = _collect_known_secret_names()
    seen = set(ordered_names)
    for name in sorted(known_names):
        if name not in seen:
            ordered_names.append(name)
            seen.add(name)

    secrets: list[SecretInfo] = []
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
    task,
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
        issue.name.split(":", 1)[1]: issue.message
        for issue in config_status.issues
        if issue.name.startswith("model:")
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
            provider = config["provider"]
            model_string = config["model_string"]
            capabilities = list(config.get("capabilities", ["text"]) or ["text"])
            dimensions = config.get("dimensions")
            user_editable = config.get("user_editable", True)
            description = config.get("description")

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
                requires_secrets = list(
                    getattr(config, "requires_secrets", [])
                    or getattr(config, "requires_env", [])
                    or []
                )
            user_editable = getattr(config, "user_editable", False)
            chat_visible = getattr(config, "chat_visible", True)
        else:
            description = config.get("description", "")
            requires_secrets = list(
                config.get("requires_secrets") or config.get("requires_env") or []
            )
            user_editable = config.get("user_editable", False)
            chat_visible = config.get("chat_visible", True)

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

    try:
        disabled_tools = get_disabled_tool_names()
    except Exception:
        disabled_tools = []

    return MetadataResponse(
        vaults=vaults,
        models=models,
        tools=tools,
        settings={
            "disabled_tools": disabled_tools,
            "default_chat_mode": get_default_chat_mode(),
            "default_model_thinking": getattr(
                get_general_settings().get("default_model_thinking"), "value", "default"
            ),
            "auto_cache_max_tokens": getattr(
                get_general_settings().get("auto_cache_max_tokens"), "value", 0
            ),
        },
        default_context_script=default_context_script,
    )
