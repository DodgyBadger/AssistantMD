"""
API endpoint implementations for the AssistantMD system.
"""


import json
from typing import List

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic_ai import BinaryContent

from core.logger import UnifiedLogger
from core.llm.openai_oauth import OPENAI_OAUTH_LOOPBACK_REDIRECT_URI
from core.runtime.state import get_runtime_context, RuntimeStateError
from core.chat.executor import (
    ChatCapabilityError,
    ChatContextTemplateError,
    ChatModelRequestLimitError,
    ChatToolCallLimitError,
    UploadedImageAttachment,
    execute_chat_prompt,
    execute_chat_prompt_stream,
)
from core.llm.thinking import normalize_thinking_value, thinking_value_to_label

from .models import (
    WorkflowLoadErrorsResponse,
    CachePurgeResponse,
    SystemTemplateSeedResponse,
    SystemMigrationRunRequest,
    SystemMigrationRunResponse,
    SystemMigrationStatusResponse,
    VaultRescanRequest,
    VaultRescanResponse,
    VaultTaskMutationsResponse,
    VaultStateCleanupResponse,
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
    WorkflowEnabledRequest,
    WorkflowEnabledResponse,
    WorkflowFileResponse,
    WorkflowFileUpdateRequest,
    ExecutionTaskCancelResponse,
    ExecutionTaskInfo,
    ExecutionTaskListResponse,
    StatusResponse,
    ChatExecuteRequest,
    ChatExecuteResponse,
    SystemLogResponse,
    SystemSettingsResponse,
    UpdateSettingsRequest,
    ModelConfigRequest,
    OpenAIOAuthCompleteRequest,
    OpenAIOAuthStartRequest,
    OpenAIOAuthStartResponse,
    ProviderConfigRequest,
    ModelInfo,
    ProviderInfo,
    OperationResult,
    SecretInfo,
    SecretUpdateRequest,
    SettingInfo,
    SettingUpdateRequest,
    MetadataResponse,
    TemplateInfo,
    ChatSessionInfo,
    ChatSessionSummaryResponse,
    ChatSessionSummaryUpdateRequest,
    ChatSessionDetailResponse,
    ChatSessionExportRequest,
    ChatSessionExportResponse,
    ChatSessionForkRequest,
    ChatSessionForkResponse,
    ChatHistoryCompactionRequest,
    ChatHistoryCompactionResponse,
    ChatHistoryCompactionStatusResponse,
    ChatSessionsPurgeRequest,
    ChatSessionsPurgeResponse,
    GoalCleanupRequest,
    GoalCleanupResponse,
    ChatSessionTitleRequest,
    ChatSessionWorkspaceRequest,
    ChatWorkspaceInfo,
    VaultDirectoryListResponse,
)
from .exceptions import (
    APIException,
    ChatCapabilityMismatchError,
    ChatContextTemplateFailureError,
    ChatModelRequestLimitExceededError,
    ChatSessionVaultMismatchError,
    ChatToolCallLimitExceededError,
)
from .utils import create_error_response, serialize_exception
from .services import (
    ChatSessionVaultMismatch,
    rescan_vaults_and_update_scheduler,
    get_system_status,
    execute_workflow_manually,
    set_workflow_enabled_state,
    get_workflow_file,
    update_workflow_file,
    get_metadata,
    list_context_templates,
    list_chat_sessions,
    get_chat_session_summary,
    update_chat_session_summary,
    delete_chat_session_summary,
    get_chat_session_detail,
    fork_chat_session,
    export_chat_session_markdown,
    compact_chat_session_history,
    get_chat_history_compaction_status,
    purge_chat_sessions,
    cleanup_goals,
    set_chat_session_title,
    set_chat_session_workspace,
    list_vault_directories,
    delete_chat_session,
    get_system_activity_log,
    get_system_settings,
    update_system_settings,
    repair_settings_from_template,
    get_general_settings_config,
    update_general_setting_value,
    get_configurable_models,
    upsert_configurable_model,
    delete_configurable_model,
    get_configurable_providers,
    start_openai_oauth_connection,
    complete_openai_oauth_callback,
    complete_openai_oauth_manual,
    disconnect_openai_oauth_connection,
    upsert_configurable_provider,
    delete_configurable_provider,
    list_secrets,
    update_secret,
    delete_secret_entry,
    scan_import_folder,
    import_url_direct,
    get_workflow_load_errors,
    purge_expired_cache,
    get_system_database_migration_status,
    run_system_database_migrations,
    refresh_system_authoring_templates,
    cancel_chat_session_task,
    cancel_execution_task,
    get_active_chat_task,
    get_execution_task,
    list_execution_tasks,
    list_workflow_tasks,
    get_vault_task_mutations,
    get_vault_snapshot_file,
    cleanup_vault_state,
    resolve_chat_session_for_request,
)
from api.import_models import (
    ImportScanRequest,
    ImportScanResponse,
    ImportJobInfo,
    ImportUrlRequest,
    ImportUrlResponse,
)

# Create API router
router = APIRouter(prefix="/api", tags=["AssistantMD API"])
logger = UnifiedLogger(tag="api-endpoints")



def _parse_form_bool(value: object, default: bool = False) -> bool:
    """Parse HTML form boolean values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _parse_form_tools(raw_tools: list[object]) -> list[str]:
    """Normalize repeated tools fields from multipart form data."""
    values = [str(item).strip() for item in raw_tools if str(item).strip()]
    if len(values) == 1 and values[0].startswith("["):
        try:
            parsed = json.loads(values[0])
        except json.JSONDecodeError:
            return values
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return values


def _looks_like_workflow_path(value: str) -> bool:
    """Return True when a workflow identifier looks like a file path instead of a workflow name."""
    normalized = value.strip().replace("\\", "/")
    return "/" in normalized or normalized.endswith((".md", ".markdown"))


async def _parse_chat_execute_payload(
    request: Request,
) -> tuple[ChatExecuteRequest, list[UploadedImageAttachment]]:
    """Parse chat request from JSON or multipart form-data."""
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("application/json"):
        payload = ChatExecuteRequest.model_validate(await request.json())
        return payload, []

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        tools = _parse_form_tools(form.getlist("tools"))
        image_paths = [str(item).strip() for item in form.getlist("image_paths") if str(item).strip()]
        payload = ChatExecuteRequest.model_validate(
            {
                "vault_name": str(form.get("vault_name") or "").strip(),
                "prompt": str(form.get("prompt") or "").strip(),
                "image_paths": image_paths,
                "session_id": str(form.get("session_id") or "").strip() or None,
                "tools": tools,
                "model": str(form.get("model") or "").strip(),
                "thinking": str(form.get("thinking") or "").strip() or None,
                "context_template": str(form.get("context_template") or "").strip() or None,
                "workspace_path": str(form.get("workspace_path") or "").strip() or None,
                "stream": _parse_form_bool(form.get("stream"), default=False),
            }
        )
        uploads: list[UploadedImageAttachment] = []
        for item in form.getlist("images"):
            if not hasattr(item, "read"):
                continue
            raw_bytes = await item.read()
            if not raw_bytes:
                continue
            media_type = str(
                getattr(item, "content_type", None) or "application/octet-stream"
            ).strip().lower()
            uploads.append(
                UploadedImageAttachment(
                    display_name=(
                        str(getattr(item, "filename", None) or "uploaded-image").strip()
                        or "uploaded-image"
                    ),
                    content=BinaryContent(data=raw_bytes, media_type=media_type),
                )
            )
        return payload, uploads

    raise ValueError(
        "Unsupported Content-Type for /api/chat/execute. Use application/json or multipart/form-data."
    )


async def _execute_chat_request(
    chat_request: ChatExecuteRequest,
    image_uploads: list[UploadedImageAttachment],
):
    """Execute chat request in streaming or non-streaming mode."""
    runtime = get_runtime_context()
    vault_path = str(runtime.config.data_root / chat_request.vault_name)
    try:
        session_id = resolve_chat_session_for_request(
            requested_session_id=chat_request.session_id,
            vault_name=chat_request.vault_name,
        )
        if chat_request.workspace_path is not None:
            set_chat_session_workspace(
                chat_request.vault_name,
                session_id,
                chat_request.workspace_path,
            )
    except ChatSessionVaultMismatch as exc:
        raise ChatSessionVaultMismatchError(
            session_id=exc.session_id,
            requested_vault=exc.requested_vault,
            bound_vault=exc.bound_vault,
        ) from exc
    resolved_thinking = normalize_thinking_value(chat_request.thinking, source_name="chat thinking")
    logger.info(
        "Chat request accepted",
        data={
            "vault_name": chat_request.vault_name,
            "session_id": session_id,
            "streaming": chat_request.stream,
            "model": chat_request.model,
            "thinking": thinking_value_to_label(resolved_thinking),
            "tools": list(chat_request.tools),
            "tools_count": len(chat_request.tools),
            "prompt_length": len(chat_request.prompt),
            "image_path_count": len(chat_request.image_paths),
            "image_upload_count": len(image_uploads),
            "context_template": chat_request.context_template,
            "workspace_path": chat_request.workspace_path,
        },
    )

    try:
        if chat_request.stream:
            stream = execute_chat_prompt_stream(
                vault_name=chat_request.vault_name,
                vault_path=vault_path,
                prompt=chat_request.prompt,
                image_paths=chat_request.image_paths,
                image_uploads=image_uploads,
                session_id=session_id,
                tools=chat_request.tools,
                model=chat_request.model,
                thinking=resolved_thinking,
                context_template=chat_request.context_template,
            )

            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "Content-Encoding": "identity",
                    "X-Accel-Buffering": "no",
                    "X-Session-ID": session_id,
                },
            )

        result = await execute_chat_prompt(
            vault_name=chat_request.vault_name,
            vault_path=vault_path,
            prompt=chat_request.prompt,
            image_paths=chat_request.image_paths,
            image_uploads=image_uploads,
            session_id=session_id,
            tools=chat_request.tools,
            model=chat_request.model,
            thinking=resolved_thinking,
            context_template=chat_request.context_template,
        )
    except ChatCapabilityError as exc:
        logger.warning(
            "Chat request capability mismatch",
            data={
                "vault_name": chat_request.vault_name,
                "session_id": session_id,
                "streaming": chat_request.stream,
                "model": chat_request.model,
                "tools": list(chat_request.tools),
                "prompt_length": len(chat_request.prompt),
                **exc.details,
            },
        )
        raise ChatCapabilityMismatchError(str(exc), details=exc.details) from exc
    except ChatContextTemplateError as exc:
        logger.warning(
            "Chat request context template failure",
            data={
                "vault_name": chat_request.vault_name,
                "session_id": session_id,
                "streaming": chat_request.stream,
                "model": chat_request.model,
                "tools": list(chat_request.tools),
                "prompt_length": len(chat_request.prompt),
                **exc.details,
            },
        )
        raise ChatContextTemplateFailureError(str(exc), details=exc.details) from exc
    except ChatToolCallLimitError as exc:
        logger.warning(
            "Chat request exceeded tool-call limit",
            data={
                "vault_name": chat_request.vault_name,
                "session_id": session_id,
                "streaming": chat_request.stream,
                "model": chat_request.model,
                "tools": list(chat_request.tools),
                "prompt_length": len(chat_request.prompt),
                **exc.details,
            },
        )
        raise ChatToolCallLimitExceededError(str(exc), details=exc.details) from exc
    except ChatModelRequestLimitError as exc:
        logger.warning(
            "Chat request exceeded model-request limit",
            data={
                "vault_name": chat_request.vault_name,
                "session_id": session_id,
                "streaming": chat_request.stream,
                "model": chat_request.model,
                "tools": list(chat_request.tools),
                "prompt_length": len(chat_request.prompt),
                **exc.details,
            },
        )
        raise ChatModelRequestLimitExceededError(str(exc), details=exc.details) from exc
    except Exception as exc:
        logger.error(
            "Chat request failed before response",
            data={
                "vault_name": chat_request.vault_name,
                "session_id": session_id,
                "streaming": chat_request.stream,
                "model": chat_request.model,
                "tools": list(chat_request.tools),
                "tools_count": len(chat_request.tools),
                "prompt_length": len(chat_request.prompt),
                "image_path_count": len(chat_request.image_paths),
                "image_upload_count": len(image_uploads),
                **serialize_exception(exc),
            },
        )
        raise

    return ChatExecuteResponse(
        response=result.response,
        session_id=result.session_id,
        message_count=result.message_count,
    )


#######################################################################
## Health & Status Endpoints
#######################################################################

@router.get("/health")
async def health_check():
    """
    Lightweight health check endpoint for Docker healthcheck and monitoring.

    Returns minimal JSON indicating system is responsive.
    Use /api/status for comprehensive system information.
    """
    try:
        # Just verify runtime context exists
        runtime = get_runtime_context()
        scheduler_running = runtime.scheduler.running if runtime.scheduler else False

        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "scheduler_running": scheduler_running
            }
        )
    except RuntimeStateError:
        # Runtime not initialized yet - still starting up
        return JSONResponse(
            status_code=503,
            content={
                "status": "starting",
                "scheduler_running": False
            }
        )
    except Exception:
        # Something is wrong
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "scheduler_running": False
            }
        )


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """
    Get current system status including vault discovery, scheduler status, and system health.
    
    Returns comprehensive information about:
    - Discovered vaults and their workflow counts
    - Scheduler status and job information  
    - System health indicators
    """
    try:
        # Try to get scheduler from runtime context
        scheduler = None
        try:
            runtime = get_runtime_context()
            scheduler = runtime.scheduler
        except RuntimeStateError:
            pass  # Runtime context not available - status will show scheduler as stopped
        
        # Get comprehensive system status
        status = await get_system_status(scheduler)
        return status
        
    except Exception as e:
        return create_error_response(e)


@router.get("/system/activity-log", response_model=SystemLogResponse)
async def system_activity_log(limit_bytes: int = 65_536):
    """
    Retrieve the system activity log, optionally truncated to the provided limit.
    """
    try:
        return await get_system_activity_log(limit_bytes)
    except Exception as e:
        return create_error_response(e)


#######################################################################
## Execution Task Endpoints
#######################################################################

@router.get("/tasks", response_model=ExecutionTaskListResponse)
async def execution_tasks(
    kind: str | None = None,
    scope: str | None = None,
    include_terminal: bool = True,
):
    """List process-local execution task snapshots."""
    try:
        return await list_execution_tasks(
            kind=kind,
            scope=scope,
            include_terminal=include_terminal,
        )
    except Exception as e:
        return create_error_response(e)


@router.get("/tasks/{task_id}", response_model=ExecutionTaskInfo)
async def execution_task(task_id: str):
    """Return one process-local execution task snapshot."""
    try:
        return await get_execution_task(task_id)
    except Exception as e:
        return create_error_response(e)


@router.post("/tasks/{task_id}/cancel", response_model=ExecutionTaskCancelResponse)
async def cancel_task(task_id: str):
    """Request cancellation for one process-local execution task."""
    try:
        return await cancel_execution_task(task_id)
    except Exception as e:
        return create_error_response(e)


@router.get("/system/settings", response_model=SystemSettingsResponse)
async def system_settings():
    """Return the current settings configuration file."""
    try:
        return await get_system_settings()
    except Exception as e:
        return create_error_response(e)


@router.put("/system/settings", response_model=SystemSettingsResponse)
async def update_system_settings_endpoint(request: UpdateSettingsRequest):
    """Validate and persist updated settings YAML content."""
    try:
        return await update_system_settings(request.content)
    except Exception as e:
        return create_error_response(e)


@router.post("/system/settings/repair", response_model=SystemSettingsResponse)
async def repair_system_settings():
    """Merge missing settings from template into active settings (with backup)."""
    try:
        return repair_settings_from_template()
    except Exception as e:
        return create_error_response(e)


@router.get("/system/settings/general", response_model=List[SettingInfo])
async def list_general_settings():
    """List general (non-secret) settings entries."""
    try:
        return get_general_settings_config()
    except Exception as e:
        return create_error_response(e)


@router.put("/system/settings/general/{setting_key}", response_model=SettingInfo)
async def update_general_setting(setting_key: str, request: SettingUpdateRequest):
    """Update a general setting value."""
    try:
        return update_general_setting_value(setting_key, request)
    except Exception as e:
        return create_error_response(e)


#######################################################################
## Import Endpoints
#######################################################################


@router.post("/import/scan", response_model=ImportScanResponse)
async def import_scan(request: ImportScanRequest):
    try:
        jobs, skipped = await scan_import_folder(
            vault=request.vault,
            queue_only=request.queue_only,
            strategies=request.strategies,
            capture_ocr_images=request.capture_ocr_images,
            pdf_mode=request.pdf_mode,
        )
        job_infos = [
            ImportJobInfo(
                id=job.id,
                source_uri=job.source_uri,
                vault=job.vault or request.vault,
                status=job.status,
                error=job.error,
                outputs=job.outputs,
            )
            for job in jobs
        ]
        return ImportScanResponse(jobs_created=job_infos, skipped=skipped)
    except Exception as e:
        return create_error_response(e)


@router.post("/import/url", response_model=ImportUrlResponse)
async def import_url(request: ImportUrlRequest):
    try:
        job = await import_url_direct(
            vault=request.vault,
            url=request.url,
            clean_html=request.clean_html,
        )
        return ImportUrlResponse(
            id=job.id,
            source_uri=job.source_uri,
            vault=job.vault or request.vault,
            status=job.status,
            error=job.error,
            outputs=job.outputs,
        )
    except Exception as e:
        return create_error_response(e)


@router.get("/system/models", response_model=List[ModelInfo])
async def list_models():
    """List all model configuration entries with availability metadata."""
    try:
        return get_configurable_models()
    except Exception as e:
        return create_error_response(e)


@router.put("/system/models/{model_name}", response_model=ModelInfo)
async def upsert_model(model_name: str, request: ModelConfigRequest):
    """Create or update a model configuration entry."""
    try:
        return upsert_configurable_model(model_name, request)
    except Exception as e:
        return create_error_response(e)


@router.delete("/system/models/{model_name}", response_model=OperationResult)
async def delete_model(model_name: str):
    """Delete a user-editable model configuration entry."""
    try:
        return delete_configurable_model(model_name)
    except Exception as e:
        return create_error_response(e)


@router.get("/system/providers", response_model=List[ProviderInfo])
async def list_providers():
    """List provider configurations."""
    try:
        return get_configurable_providers()
    except Exception as e:
        return create_error_response(e)


@router.post(
    "/system/providers/openai/oauth/start",
    response_model=OpenAIOAuthStartResponse,
)
async def start_openai_oauth(payload: OpenAIOAuthStartRequest):
    """Start an OpenAI OAuth connection attempt."""
    try:
        return start_openai_oauth_connection(
            payload,
            default_redirect_uri=OPENAI_OAUTH_LOOPBACK_REDIRECT_URI,
        )
    except Exception as e:
        return create_error_response(e)


@router.get("/system/providers/openai/oauth/callback", response_model=ProviderInfo)
async def complete_openai_oauth_callback_endpoint(code: str, state: str):
    """Complete OpenAI OAuth from callback query parameters."""
    try:
        return await complete_openai_oauth_callback(code=code, state=state)
    except Exception as e:
        return create_error_response(e)


@router.post("/system/providers/openai/oauth/complete", response_model=ProviderInfo)
async def complete_openai_oauth_manual_endpoint(request: OpenAIOAuthCompleteRequest):
    """Complete OpenAI OAuth from a pasted redirect URL or code/state pair."""
    try:
        return await complete_openai_oauth_manual(request)
    except Exception as e:
        return create_error_response(e)


@router.get("/system/providers/openai/oauth/status", response_model=ProviderInfo)
async def get_openai_oauth_status_endpoint():
    """Return OpenAI provider status including sanitized OAuth metadata."""
    try:
        return next(
            provider
            for provider in get_configurable_providers()
            if provider.name == "openai"
        )
    except Exception as e:
        return create_error_response(e)


@router.delete("/system/providers/openai/oauth", response_model=OperationResult)
async def disconnect_openai_oauth_endpoint():
    """Disconnect OpenAI OAuth without changing provider auth mode."""
    try:
        return disconnect_openai_oauth_connection()
    except Exception as e:
        return create_error_response(e)


@router.put("/system/providers/{provider_name}", response_model=ProviderInfo)
async def upsert_provider(provider_name: str, request: ProviderConfigRequest):
    """Create or update a provider configuration."""
    try:
        return upsert_configurable_provider(provider_name, request)
    except Exception as e:
        return create_error_response(e)


@router.delete("/system/providers/{provider_name}", response_model=OperationResult)
async def delete_provider(provider_name: str):
    """Delete a user-editable provider configuration."""
    try:
        return delete_configurable_provider(provider_name)
    except Exception as e:
        return create_error_response(e)


@router.get("/system/secrets", response_model=List[SecretInfo])
async def list_secrets_endpoint():
    """List stored secrets and whether they currently have values."""
    try:
        return list_secrets()
    except Exception as e:
        return create_error_response(e)


@router.put("/system/secrets", response_model=OperationResult)
async def set_secret_endpoint(request: SecretUpdateRequest):
    """Create, update, or clear a stored secret."""
    try:
        return update_secret(request)
    except Exception as e:
        return create_error_response(e)


@router.delete("/system/secrets/{secret_name}", response_model=OperationResult)
async def delete_secret_endpoint(secret_name: str):
    """Delete a stored secret entry entirely."""
    try:
        return delete_secret_entry(secret_name)
    except Exception as e:
        return create_error_response(e)


@router.post("/system/cache/purge-expired", response_model=CachePurgeResponse)
async def purge_expired_cache_endpoint():
    """Manually delete expired cache artifacts."""
    try:
        return purge_expired_cache()
    except Exception as e:
        return create_error_response(e)


@router.post("/system/goals/cleanup", response_model=GoalCleanupResponse)
async def cleanup_goals_endpoint(request: GoalCleanupRequest):
    """Manually delete old completed or cancelled goals for a vault."""
    try:
        return cleanup_goals(
            request.vault_name,
            status=request.status,
            older_than_days=request.older_than_days,
        )
    except Exception as e:
        return create_error_response(e)


@router.get("/system/migrations/status", response_model=SystemMigrationStatusResponse)
async def get_system_database_migration_status_endpoint():
    """Inspect registered system database migrations."""
    try:
        return get_system_database_migration_status()
    except Exception as e:
        return create_error_response(e)


@router.post("/system/migrations/run", response_model=SystemMigrationRunResponse)
async def run_system_database_migrations_endpoint(request: SystemMigrationRunRequest = SystemMigrationRunRequest()):
    """Run registered system database migrations."""
    try:
        return run_system_database_migrations(backup=request.backup)
    except Exception as e:
        return create_error_response(e)


@router.post("/system/authoring/seed-refresh", response_model=SystemTemplateSeedResponse)
async def refresh_system_authoring_templates_endpoint():
    """Manually refresh packaged system Authoring templates."""
    try:
        return refresh_system_authoring_templates()
    except Exception as e:
        return create_error_response(e)


@router.post("/vault-state/cleanup", response_model=VaultStateCleanupResponse)
async def cleanup_vault_state_endpoint():
    """Manually delete expired vault-state task safety artifacts."""
    try:
        return cleanup_vault_state()
    except Exception as e:
        return create_error_response(e)


#######################################################################
## Vault Management Endpoints  
#######################################################################

@router.post("/vaults/rescan", response_model=VaultRescanResponse)
async def rescan_vaults(request: VaultRescanRequest = VaultRescanRequest()):
    """
    Force immediate rediscovery of all vault directories and reload workflow configurations.
    
    This endpoint:
    - Rediscovers all vault directories
    - Reloads all workflow configurations from discovered vaults
    - Updates the scheduler with new/modified/removed workflow jobs
    - Returns summary of discovered vaults and workflows
    """
    try:
        # Try to get scheduler from runtime context
        scheduler = None
        try:
            runtime = get_runtime_context()
            scheduler = runtime.scheduler
        except RuntimeStateError:
            pass  # Runtime context not available - rescan will reload configs but not update jobs

        # Perform the rescan operation
        results = await rescan_vaults_and_update_scheduler(scheduler)
        metadata = await get_metadata()

        return VaultRescanResponse(
            success=True,
            vaults_discovered=results['vaults_discovered'],
            workflows_loaded=results['workflows_loaded'],
            enabled_workflows=results['enabled_workflows'],
            scheduler_jobs_synced=results['scheduler_jobs_synced'],
            message=f"Rescan completed successfully: {results['vaults_discovered']} vaults, {results['enabled_workflows']} enabled workflows, {results['scheduler_jobs_synced']} jobs synced",
            metadata=metadata,
        )
        
    except Exception as e:
        return create_error_response(e)


@router.get("/vaults/{vault_name}/task-mutations", response_model=VaultTaskMutationsResponse)
async def vault_task_mutations(
    vault_name: str,
    limit: int = 50,
    task_id: str | None = None,
    include_expired: bool = False,
    operation: str | None = None,
):
    """Return recent durable task file mutations for one vault."""
    try:
        return get_vault_task_mutations(
            vault_name=vault_name,
            limit=limit,
            task_id=task_id,
            include_expired=include_expired,
            operation=operation,
        )
    except Exception as e:
        return create_error_response(e)


@router.get("/vault-state/snapshots/{snapshot_id}/content")
async def vault_snapshot_content(snapshot_id: int):
    """Serve one retained vault-state file snapshot inline."""
    try:
        snapshot = get_vault_snapshot_file(snapshot_id)
        return FileResponse(
            snapshot.path,
            media_type=snapshot.media_type,
            filename=snapshot.filename,
            content_disposition_type="inline",
        )
    except Exception as e:
        return create_error_response(e)




@router.post("/workflows/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow(request: ExecuteWorkflowRequest):
    """
    Execute a specific workflow manually.
    """
    try:
        result = await execute_workflow_manually(
            request.global_id,
            request.expect_failure,
            vault_name=request.vault_name,
        )
        response = ExecuteWorkflowResponse(**result)
        return response
    except Exception as e:
        return create_error_response(e)


@router.post("/workflows/enabled", response_model=WorkflowEnabledResponse)
async def set_workflow_enabled(request: WorkflowEnabledRequest):
    """Set a workflow enabled flag in frontmatter."""
    try:
        return await set_workflow_enabled_state(request.global_id, request.enabled)
    except Exception as e:
        return create_error_response(e)


@router.get("/workflows/file", response_model=WorkflowFileResponse)
async def workflow_file(global_id: str):
    """Return editable workflow file content."""
    try:
        return get_workflow_file(global_id)
    except Exception as e:
        return create_error_response(e)


@router.put("/workflows/file", response_model=WorkflowFileResponse)
async def save_workflow_file(global_id: str, request: WorkflowFileUpdateRequest):
    """Replace workflow file content and reload workflows."""
    try:
        return await update_workflow_file(
            global_id,
            content=request.content,
            expected_sha256=request.expected_sha256,
        )
    except Exception as e:
        return create_error_response(e)


@router.get("/workflows/load-errors", response_model=WorkflowLoadErrorsResponse)
async def workflow_load_errors(vault_name: str | None = None, workflow_name: str | None = None):
    """Return workflow load errors without exposing the full system status payload."""
    try:
        if workflow_name and _looks_like_workflow_path(workflow_name):
            raise APIException(
                status_code=400,
                error_type="InvalidWorkflowNameFilter",
                message=(
                    "workflow_load_errors expects a workflow name, not a file path. "
                    "Use compile-only workflow testing for draft files under AssistantMD/Workflows/."
                ),
                details={"workflow_name": workflow_name},
            )
        return WorkflowLoadErrorsResponse(
            errors=get_workflow_load_errors(vault_name=vault_name, workflow_name=workflow_name)
        )
    except Exception as e:
        return create_error_response(e)


@router.get("/workflows/tasks", response_model=ExecutionTaskListResponse)
async def workflow_tasks(vault_name: str | None = None):
    """List process-local workflow execution task snapshots."""
    try:
        return await list_workflow_tasks(vault_name=vault_name)
    except Exception as e:
        return create_error_response(e)


#######################################################################
## Chat Execution Endpoints
#######################################################################

@router.post("/chat/execute")
async def chat_execute(request: Request):
    """
    Execute chat prompt with user-selected tools and model.

    Supports both streaming and non-streaming responses based on the 'stream' parameter.
    - stream=false (default): Returns complete response as JSON
    - stream=true: Returns SSE (Server-Sent Events) stream with incremental chunks

    Session ID is automatically generated based on vault name and timestamp.
    Follows OpenAI API conventions for compatibility with standard clients.
    """
    try:
        chat_request, image_uploads = await _parse_chat_execute_payload(request)
        return await _execute_chat_request(chat_request, image_uploads)
    except Exception as e:
        if isinstance(e, APIException):
            logger.warning(
                "Chat endpoint request rejected",
                data={
                    "path": str(request.url.path),
                    "method": request.method,
                    "error_type": e.error_type,
                    "message": str(e.detail),
                    "details": e.details,
                },
            )
            return create_error_response(e)
        logger.error(
            "Chat endpoint request failed",
            data={
                "path": str(request.url.path),
                "method": request.method,
                **serialize_exception(e),
            },
        )
        return create_error_response(e)


@router.get("/metadata", response_model=MetadataResponse)
async def metadata():
    """
    Get metadata for UI (vaults, models, tools).
    """
    try:
        return await get_metadata()
    except Exception as e:
        return create_error_response(e)


@router.get("/context/templates", response_model=List[TemplateInfo])
async def context_templates(vault_name: str):
    """
    List available context templates for a vault (vault + system sources).
    """
    try:
        return list_context_templates(vault_name)
    except Exception as e:
        return create_error_response(e)


@router.get("/vaults/{vault_name}/directories", response_model=VaultDirectoryListResponse)
async def vault_directories(vault_name: str, path: str | None = None):
    """Return child directories for workspace selection."""
    try:
        return list_vault_directories(vault_name, path)
    except Exception as e:
        return create_error_response(e)


@router.get("/chat/sessions", response_model=List[ChatSessionInfo])
async def chat_sessions(vault_name: str):
    """
    List persisted chat sessions for a vault ordered by latest activity.
    """
    try:
        return list_chat_sessions(vault_name)
    except Exception as e:
        return create_error_response(e)


@router.get("/chat/sessions/{session_id}/active-task", response_model=ExecutionTaskInfo)
async def chat_session_active_task(session_id: str):
    """Return the active process-local execution task for a chat session."""
    try:
        return await get_active_chat_task(session_id)
    except Exception as e:
        return create_error_response(e)


@router.post("/chat/sessions/{session_id}/cancel", response_model=ExecutionTaskCancelResponse)
async def cancel_chat_session(session_id: str):
    """Request cancellation for the active process-local task in a chat session."""
    try:
        return await cancel_chat_session_task(session_id)
    except Exception as e:
        return create_error_response(e)


@router.get("/chat/sessions/{session_id}/summary", response_model=ChatSessionSummaryResponse)
async def chat_session_summary(session_id: str, vault_name: str):
    """Return a lightweight summary preview for one chat session."""
    try:
        return get_chat_session_summary(vault_name, session_id)
    except Exception as e:
        return create_error_response(e)


@router.put("/chat/sessions/{session_id}/summary", response_model=ChatSessionSummaryResponse)
async def update_chat_session_summary_endpoint(
    session_id: str,
    vault_name: str,
    request: ChatSessionSummaryUpdateRequest,
):
    """Manually update one session summary record."""
    try:
        return await update_chat_session_summary(
            vault_name=vault_name,
            session_id=session_id,
            data=request.model_dump(mode="python"),
        )
    except Exception as e:
        return create_error_response(e)


@router.delete("/chat/sessions/{session_id}/summary")
async def delete_chat_session_summary_endpoint(session_id: str, vault_name: str):
    """Delete one session summary record without deleting the chat session."""
    try:
        return delete_chat_session_summary(vault_name, session_id)
    except Exception as e:
        return create_error_response(e)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def chat_session_detail(session_id: str, vault_name: str):
    """
    Load one persisted chat session for UI rehydration.
    """
    try:
        return get_chat_session_detail(vault_name, session_id)
    except Exception as e:
        return create_error_response(e)


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session_endpoint(session_id: str, vault_name: str):
    """Delete one chat session from the canonical store."""
    try:
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / vault_name)
        delete_chat_session(vault_name, vault_path, session_id)
        return {"session_id": session_id, "deleted": True}
    except Exception as e:
        return create_error_response(e)


@router.patch("/chat/sessions/{session_id}/title")
async def set_session_title(session_id: str, request: ChatSessionTitleRequest):
    """Set or clear the user-defined title for a chat session."""
    try:
        title = (request.title or "").strip() or None
        set_chat_session_title(request.vault_name, session_id, title)
        return {"session_id": session_id, "title": title}
    except Exception as e:
        return create_error_response(e)


@router.patch("/chat/sessions/{session_id}/workspace", response_model=ChatWorkspaceInfo | None)
async def set_session_workspace(session_id: str, request: ChatSessionWorkspaceRequest):
    """Set or clear the workspace path for a chat session."""
    try:
        return set_chat_session_workspace(request.vault_name, session_id, request.path)
    except Exception as e:
        return create_error_response(e)


@router.post("/chat/sessions/{session_id}/fork", response_model=ChatSessionForkResponse)
async def fork_chat_session_endpoint(session_id: str, request: ChatSessionForkRequest):
    """Fork one persisted chat session through a specific message sequence."""
    try:
        return fork_chat_session(
            vault_name=request.vault_name,
            source_session_id=session_id,
            through_sequence_index=request.through_sequence_index,
        )
    except Exception as e:
        return create_error_response(e)


@router.post("/chat/sessions/{session_id}/export", response_model=ChatSessionExportResponse)
async def export_chat_session_endpoint(session_id: str, request: ChatSessionExportRequest):
    """Export one persisted chat session transcript into the owning vault."""
    try:
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / request.vault_name)
        return export_chat_session_markdown(request.vault_name, vault_path, session_id)
    except Exception as e:
        return create_error_response(e)


@router.get("/chat/sessions/{session_id}/compaction-status", response_model=ChatHistoryCompactionStatusResponse)
async def chat_history_compaction_status_endpoint(session_id: str, vault_name: str):
    """Return compaction status for one persisted chat session."""
    try:
        return await get_chat_history_compaction_status(vault_name, session_id)
    except Exception as e:
        return create_error_response(e)


@router.post("/chat/sessions/{session_id}/compact", response_model=ChatHistoryCompactionResponse)
async def compact_chat_history_endpoint(session_id: str, request: ChatHistoryCompactionRequest):
    """Compact one persisted chat session into a summary plus recent turns."""
    try:
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / request.vault_name)
        return await compact_chat_session_history(
            request.vault_name,
            vault_path,
            session_id,
            focus=request.focus,
        )
    except Exception as e:
        return create_error_response(e)


@router.post("/chat/sessions/purge", response_model=ChatSessionsPurgeResponse)
async def purge_chat_sessions_endpoint(request: ChatSessionsPurgeRequest):
    """
    Delete old chat sessions and their transcript files for a vault.
    """
    try:
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / request.vault_name)
        return purge_chat_sessions(
            request.vault_name,
            vault_path,
            older_than_days=request.older_than_days,
        )
    except Exception as e:
        return create_error_response(e)


#######################################################################
## Error Handlers (Note: These will be registered with the main FastAPI app)
#######################################################################

def register_exception_handlers(app):
    """Register exception handlers with the FastAPI app."""
    
    @app.exception_handler(APIException)
    async def api_exception_handler(request, exc: APIException):
        """Handle API-specific exceptions with proper error responses."""
        return create_error_response(exc)

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc: Exception):
        """Handle unexpected exceptions with generic error responses."""
        return create_error_response(exc)
