"""
API endpoint implementations for the AssistantMD system.
"""


import json
from typing import List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic_ai import BinaryContent

from core.runtime.state import get_runtime_context, RuntimeStateError
from core.llm.session_manager import SessionManager
from core.llm.chat_executor import (
    UploadedImageAttachment,
    execute_chat_prompt,
    execute_chat_prompt_stream,
)

from .models import (
    VaultRescanRequest,
    VaultRescanResponse,
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
    StatusResponse,
    ChatExecuteRequest,
    ChatExecuteResponse,
    SystemLogResponse,
    SystemSettingsResponse,
    UpdateSettingsRequest,
    ModelConfigRequest,
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
)
from .exceptions import APIException
from .utils import create_error_response, generate_session_id
from .services import (
    rescan_vaults_and_update_scheduler,
    get_system_status,
    execute_workflow_manually,
    get_metadata,
    list_context_templates,
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
    upsert_configurable_provider,
    delete_configurable_provider,
    list_secrets,
    update_secret,
    delete_secret_entry,
    scan_import_folder,
    import_url_direct,
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

# Create module-level session manager for chat conversations
session_manager = SessionManager()


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
                "context_template": str(form.get("context_template") or "").strip() or None,
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
    session_id = chat_request.session_id or generate_session_id(chat_request.vault_name)

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
            session_manager=session_manager,
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
        session_manager=session_manager,
        context_template=chat_request.context_template,
    )

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
        jobs, skipped = scan_import_folder(
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
        job = import_url_direct(
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




@router.post("/workflows/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow(request: ExecuteWorkflowRequest):
    """
    Execute a specific workflow manually.
    
    Args:
        request: ExecuteWorkflowRequest with global_id and optional step selection
    """
    try:
        result = await execute_workflow_manually(request.global_id, request.step_name)
        response = ExecuteWorkflowResponse(**result)
        return response
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
