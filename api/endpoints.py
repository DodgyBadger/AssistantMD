"""
API endpoint implementations for the AssistantMD system.
"""


from typing import List

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from core.runtime.state import get_runtime_context, RuntimeStateError
from core.llm.session_manager import SessionManager
from core.llm.chat_executor import execute_chat_prompt, execute_chat_prompt_stream

from .models import (
    VaultRescanRequest,
    VaultRescanResponse,
    ExecuteAssistantRequest,
    ExecuteAssistantResponse,
    StatusResponse,
    ChatExecuteRequest,
    ChatExecuteResponse,
    ChatMetadataResponse,
    ChatSessionTransformRequest,
    ChatSessionTransformResponse,
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
)
from .exceptions import APIException
from .utils import create_error_response, generate_session_id
from .services import (
    rescan_vaults_and_update_scheduler,
    get_system_status,
    execute_assistant_manually,
    get_chat_metadata,
    compact_conversation_history,
    start_assistant_creation,
    get_system_activity_log,
    get_system_settings,
    update_system_settings,
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
)

# Create API router
router = APIRouter(prefix="/api", tags=["AssistantMD API"])

# Create module-level session manager for chat conversations
session_manager = SessionManager()


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
    - Discovered vaults and their assistant counts
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
    Force immediate rediscovery of all vault directories and reload assistant configurations.
    
    This endpoint:
    - Rediscovers all vault directories
    - Reloads all assistant configurations from discovered vaults
    - Updates the scheduler with new/modified/removed assistant jobs
    - Returns summary of discovered vaults and assistants
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
        
        # Format the response
        response = VaultRescanResponse(
            success=True,
            vaults_discovered=results['vaults_discovered'],
            assistants_loaded=results['assistants_loaded'],
            enabled_assistants=results['enabled_assistants'],
            scheduler_jobs_synced=results['scheduler_jobs_synced'],
            message=f"Rescan completed successfully: {results['vaults_discovered']} vaults, {results['enabled_assistants']} enabled assistants, {results['scheduler_jobs_synced']} jobs synced"
        )
        
        return response
        
    except Exception as e:
        return create_error_response(e)




@router.post("/assistants/execute", response_model=ExecuteAssistantResponse)
async def execute_assistant(request: ExecuteAssistantRequest):
    """
    Execute a specific assistant workflow manually.
    
    This endpoint enables on-demand execution of any assistant workflow,
    bypassing the normal scheduled execution. Useful for testing, debugging,
    or when immediate results are needed.
    
    Args:
        request: ExecuteAssistantRequest with global_id and optional force flag
        
    Returns:
        ExecuteAssistantResponse with execution results and timing
        
    Raises:
        404: If assistant global_id not found
        500: If workflow execution fails
    """
    try:        
        # Execute the assistant workflow
        result = await execute_assistant_manually(request.global_id, request.step_name)
        
        # Format the response
        response = ExecuteAssistantResponse(**result)
        
        return response
        
    except Exception as e:
        return create_error_response(e)


#######################################################################
## Chat Execution Endpoints
#######################################################################

@router.post("/chat/execute")
async def chat_execute(request: ChatExecuteRequest):
    """
    Execute chat prompt with user-selected tools and model.

    Supports both streaming and non-streaming responses based on the 'stream' parameter.
    - stream=false (default): Returns complete response as JSON
    - stream=true: Returns SSE (Server-Sent Events) stream with incremental chunks

    Session ID is automatically generated based on vault name and timestamp.
    Follows OpenAI API conventions for compatibility with standard clients.
    """
    try:
        # Get vault path from runtime context
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / request.vault_name)

        # Generate session ID if not provided (first turn), otherwise reuse existing
        session_id = request.session_id or generate_session_id(request.vault_name)

        # Handle streaming vs non-streaming
        if request.stream:
            # Streaming response (SSE format)
            stream = execute_chat_prompt_stream(
                vault_name=request.vault_name,
                vault_path=vault_path,
                prompt=request.prompt,
                session_id=session_id,
                tools=request.tools,
                model=request.model,
                use_conversation_history=request.use_conversation_history,
                session_manager=session_manager,
                instructions=request.instructions,
                session_type=request.session_type
            )

            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    # Disable compression to avoid browser buffering of SSE chunks
                    "Content-Encoding": "identity",
                    # Prevent reverse proxies (nginx, etc.) from buffering the stream
                    "X-Accel-Buffering": "no",
                    "X-Session-ID": session_id  # Return session ID in header for client tracking
                }
            )
        else:
            # Non-streaming response (JSON)
            result = await execute_chat_prompt(
                vault_name=request.vault_name,
                vault_path=vault_path,
                prompt=request.prompt,
                session_id=session_id,
                tools=request.tools,
                model=request.model,
                use_conversation_history=request.use_conversation_history,
                session_manager=session_manager,
                instructions=request.instructions,
                session_type=request.session_type
            )

            return ChatExecuteResponse(
                response=result.response,
                session_id=result.session_id,
                message_count=result.message_count
            )
    except Exception as e:
        return create_error_response(e)


@router.get("/chat/metadata", response_model=ChatMetadataResponse)
async def chat_metadata():
    """
    Get metadata for chat UI configuration.

    Returns available vaults, models, and tools dynamically loaded
    from runtime context and settings.yaml.
    """
    try:
        return await get_chat_metadata()
    except Exception as e:
        return create_error_response(e)


@router.post("/chat/compact", response_model=ChatSessionTransformResponse)
async def compact_chat_history(request: ChatSessionTransformRequest):
    """
    Compact conversation history by summarizing with LLM.

    Replaces the full conversation history with a concise summary,
    preserving context while reducing token count.
    """
    try:
        result = await compact_conversation_history(
            session_id=request.session_id,
            vault_name=request.vault_name,
            model=request.model,
            user_instructions=request.user_instructions,
            session_manager=session_manager
        )

        return ChatSessionTransformResponse(
            success=True,
            summary=result["summary"],
            original_message_count=result["original_count"],
            compacted_to=result["compacted_count"],
            new_session_id=result["new_session_id"],
            message=f"History compacted from {result['original_count']} to {result['compacted_count']} messages"
        )
    except Exception as e:
        return create_error_response(e)


@router.post("/chat/create-assistant", response_model=ChatSessionTransformResponse)
async def create_assistant(request: ChatSessionTransformRequest):
    """
    Start interactive assistant creation conversation.

    Creates a new session focused on designing and creating a step workflow assistant.
    Handles both scenarios:
    - Existing conversation: Summarizes with creation focus, starts new session
    - No/minimal conversation: Starts fresh with assistant creation guidance

    The LLM will ask questions to gather requirements and ultimately use tools
    to read documentation and write the assistant file.
    """
    try:
        # Get vault path from runtime context
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / request.vault_name)

        result = await start_assistant_creation(
            session_id=request.session_id,
            vault_name=request.vault_name,
            model=request.model,
            user_instructions=request.user_instructions,
            session_manager=session_manager,
            vault_path=vault_path
        )

        return ChatSessionTransformResponse(
            success=True,
            summary=result["summary"],
            original_message_count=result["original_count"],
            compacted_to=result["compacted_count"],
            new_session_id=result["new_session_id"],
            message="Assistant creation started - continue conversation in new session"
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
