"""
Pydantic models for API request and response schemas.
"""

from __future__ import annotations

from typing import List, Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field


#######################################################################
## Request Models
#######################################################################

class VaultCreateRequest(BaseModel):
    """Request model for creating a new vault."""
    name: str = Field(..., min_length=1, max_length=100, description="Name of the vault to create")


class VaultRescanRequest(BaseModel):
    """Request model for vault rescan operation (empty body)."""
    pass


class ExecuteWorkflowRequest(BaseModel):
    """Request model for manually executing a workflow."""
    global_id: str = Field(..., description="Workflow global ID (vault/name format)")
    step_name: Optional[str] = Field(None, description="Execute only specified step (e.g. 'STEP1')")


class ChatExecuteRequest(BaseModel):
    """Request model for chat execution."""
    vault_name: str = Field(..., description="Vault context for execution")
    prompt: str = Field(..., min_length=1, description="User prompt text")
    session_id: Optional[str] = Field(None, description="Session ID (generated if not provided)")
    tools: List[str] = Field(..., description="List of tool names to enable")
    model: str = Field(..., description="Model name to use")
    instructions: Optional[str] = Field(None, description="Optional system instructions")
    session_type: str = Field("regular", description="Chat mode: 'regular', 'workflow_creation', or 'endless'")
    context_template: Optional[str] = Field(None, description="Optional context compiler template name")
    stream: bool = Field(False, description="Whether to stream the response (SSE format)")


class ChatSessionTransformRequest(BaseModel):
    """Request model for chat session transformations (compact, assistant creation, etc)."""
    session_id: str = Field(..., description="Session ID to transform")
    vault_name: str = Field(..., description="Vault name for session")
    model: str = Field(..., description="Model to use for transformation")
    user_instructions: Optional[str] = Field(None, description="Optional user guidance for transformation")


#######################################################################
## Response Models
#######################################################################

class VaultInfo(BaseModel):
    """Information about a single vault."""
    name: str = Field(..., description="Vault name")
    path: str = Field(..., description="Full path to vault directory")
    workflow_count: int = Field(..., description="Number of workflows in this vault")
    workflows: List[str] = Field(default_factory=list, description="List of workflow names")


class SchedulerInfo(BaseModel):
    """Information about the scheduler status."""
    running: bool = Field(..., description="Whether the scheduler is running")
    total_jobs: int = Field(..., description="Total number of scheduled jobs")
    enabled_workflows: int = Field(..., description="Number of enabled workflows")
    disabled_workflows: int = Field(..., description="Number of disabled workflows")
    job_details: List[Dict] = Field(default_factory=list, description="Detailed job information from APScheduler")


class SystemInfo(BaseModel):
    """Information about system health."""
    startup_time: datetime = Field(..., description="When the system started")
    last_config_reload: Optional[datetime] = Field(None, description="Last time configuration was reloaded")
    data_root: str = Field(..., description="Root directory for vault data")


class ConfigurationIssueInfo(BaseModel):
    """Configuration issue surfaced to the API."""

    name: str = Field(..., description="Identifier for the issue (e.g., tool:web_search)")
    message: str = Field(..., description="Human-readable description of the issue")
    severity: str = Field(..., description="Issue severity (error or warning)")


class ConfigurationStatusInfo(BaseModel):
    """Aggregated configuration health information for API clients."""

    issues: List[ConfigurationIssueInfo] = Field(default_factory=list, description="Configuration issues discovered during validation")
    tool_availability: Dict[str, bool] = Field(default_factory=dict, description="Tool availability keyed by tool name")
    model_availability: Dict[str, bool] = Field(default_factory=dict, description="Model availability keyed by model name")


class StatusResponse(BaseModel):
    """Response model for system status endpoint."""

    vaults: List[VaultInfo] = Field(default_factory=list, description="Information about discovered vaults")
    scheduler: SchedulerInfo = Field(..., description="Scheduler status information")
    system: SystemInfo = Field(..., description="System health information")
    total_vaults: int = Field(..., description="Total number of discovered vaults")
    total_workflows: int = Field(..., description="Total number of workflows across all vaults")
    enabled_workflows: List["WorkflowSummary"] = Field(default_factory=list, description="List of enabled workflows with details")
    disabled_workflows: List["WorkflowSummary"] = Field(default_factory=list, description="List of disabled workflows with details")
    configuration_errors: List["ConfigurationError"] = Field(default_factory=list, description="Configuration errors encountered during loading")
    configuration_status: ConfigurationStatusInfo = Field(default_factory=ConfigurationStatusInfo, description="Aggregated configuration health information")


class VaultCreateResponse(BaseModel):
    """Response model for vault creation endpoint."""
    success: bool = Field(..., description="Whether the vault was created successfully")
    vault_name: str = Field(..., description="Name of the created vault")
    vault_path: str = Field(..., description="Full path to the created vault")
    workflow_file: str = Field(..., description="Path to the created workflow file")
    message: str = Field(..., description="Human-readable success message")


class VaultRescanResponse(BaseModel):
    """Response model for vault rescan endpoint."""
    success: bool = Field(..., description="Whether the rescan was successful")
    vaults_discovered: int = Field(..., description="Number of vaults discovered")
    workflows_loaded: int = Field(..., description="Number of workflows loaded")
    enabled_workflows: int = Field(..., description="Number of enabled workflows")
    scheduler_jobs_synced: int = Field(..., description="Number of scheduler jobs synchronized")
    message: str = Field(..., description="Human-readable success message")
    metadata: Optional["MetadataResponse"] = Field(None, description="Updated metadata after rescan")


class ExecuteWorkflowResponse(BaseModel):
    """Response model for manual workflow execution."""
    success: bool = Field(..., description="Whether execution succeeded")
    global_id: str = Field(..., description="Workflow global ID that was executed")
    execution_time_seconds: float = Field(..., description="Workflow execution time")
    output_files: List[str] = Field(default_factory=list, description="Created output file paths")
    message: str = Field(..., description="Human-readable execution summary")


class ChatExecuteResponse(BaseModel):
    """Response model for chat execution."""
    response: str = Field(..., description="The AI's response")
    session_id: str = Field(..., description="Session identifier")
    message_count: int = Field(..., description="Total messages in conversation")


class ChatSessionTransformResponse(BaseModel):
    """Response model for chat session transformations (compact, assistant creation, etc)."""
    success: bool = Field(..., description="Whether the operation succeeded")
    summary: str = Field(..., description="Generated summary text")
    original_message_count: int = Field(..., description="Number of messages before transformation")
    compacted_to: int = Field(..., description="Number of messages after transformation")
    new_session_id: str = Field(..., description="New session ID for continuing conversation")
    message: str = Field(..., description="Human-readable confirmation message")


class ModelInfo(BaseModel):
    """Model metadata for UI configuration."""

    name: str = Field(..., description="User-friendly model name")
    provider: str = Field(..., description="Provider (anthropic, openai, google, etc.)")
    model_string: str = Field(..., description="Actual model identifier")
    available: bool = Field(True, description="Whether required credentials are configured")
    user_editable: bool = Field(True, description="If the model mapping is user-editable via UI")
    description: Optional[str] = Field(None, description="Optional human-readable description")
    status_message: Optional[str] = Field(None, description="Optional availability warning or guidance")


class ToolInfo(BaseModel):
    """Tool metadata for UI configuration."""
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    requires_secrets: List[str] = Field(default_factory=list, description="Secret names required for activation")
    available: bool = Field(True, description="Whether required credentials are configured")
    user_editable: bool = Field(False, description="If the tool entry is user-editable via UI")


class ProviderInfo(BaseModel):
    """Provider configuration metadata."""

    name: str = Field(..., description="Provider name")
    api_key: Optional[str] = Field(None, description="Secret name containing the API key, if required")
    base_url: Optional[str] = Field(None, description="Secret name or direct URL for custom endpoints")
    user_editable: bool = Field(False, description="If the provider entry can be edited via UI")
    api_key_has_value: bool = Field(False, description="True if the API key secret currently has a value")
    base_url_has_value: bool = Field(False, description="True if the base URL secret or literal value is set")
    restart_required: bool = Field(
        False,
        description="True when recent edits require a full restart to take effect.",
    )


class MetadataResponse(BaseModel):
    """Unified metadata response for vaults, models, and tools."""
    vaults: List[str] = Field(..., description="Available vault names")
    models: List[ModelInfo] = Field(..., description="Available models")
    tools: List[ToolInfo] = Field(..., description="Available tools")


class TemplateInfo(BaseModel):
    """Context template metadata for UI selection."""
    name: str = Field(..., description="Template filename")
    source: str = Field(..., description="Template source: vault or system")
    path: Optional[str] = Field(None, description="Full path to template, if available")


class ModelConfigRequest(BaseModel):
    """Payload for creating or updating a model mapping."""

    provider: str = Field(..., description="Provider name the model uses")
    model_string: str = Field(..., description="Provider-specific model identifier")
    description: Optional[str] = Field(None, description="Optional description for UI display")


class ProviderConfigRequest(BaseModel):
    """Payload for creating or updating a provider configuration."""

    api_key: Optional[str] = Field(None, description="Secret name containing the provider API key")
    base_url: Optional[str] = Field(None, description="Either a direct URL or the name of a stored secret")
    api_key_value: Optional[str] = Field(None, description="Optional API key value to persist in the secrets store")
    base_url_value: Optional[str] = Field(None, description="Optional base URL value to persist in the secrets store")


class OperationResult(BaseModel):
    """Generic success response for configuration operations."""

    success: bool = Field(True, description="Whether the operation succeeded")
    message: str = Field(..., description="Human-readable summary")
    restart_required: bool = Field(
        False,
        description="True when a full restart is still required for secret changes.",
    )


class SecretInfo(BaseModel):
    """Information about a stored secret without revealing its value."""

    name: str = Field(..., description="Secret name")
    has_value: bool = Field(..., description="True if the secret currently has a value")
    stored: bool = Field(False, description="True when the secret exists in the user-writable store")


class SecretUpdateRequest(BaseModel):
    """Request payload for setting or updating a stored secret."""

    name: str = Field(..., description="Secret name")
    value: Optional[str] = Field(None, description="New value for the secret (empty to clear)")


class SystemLogResponse(BaseModel):
    """Response containing contents of the system activity log."""
    content: str = Field(..., description="Rendered contents of the activity log")
    truncated: bool = Field(False, description="Whether the log output was truncated")
    path: str = Field(..., description="Filesystem path to the activity log")
    size_bytes: int = Field(..., description="Total size of the activity log in bytes")
    shown_bytes: int = Field(..., description="Number of bytes included in this response")


class SystemSettingsResponse(BaseModel):
    """Response containing settings configuration for editing."""
    path: str = Field(..., description="Filesystem path to the active settings file")
    content: str = Field(..., description="Raw YAML content of the settings file")
    size_bytes: int = Field(..., description="Total size of the settings file in bytes")


class UpdateSettingsRequest(BaseModel):
    """Request payload when updating settings YAML content."""
    content: str = Field(..., description="New YAML content to persist")


class SettingInfo(BaseModel):
    """Information about a general (non-secret) application setting."""

    key: str = Field(..., description="Setting name")
    value: str = Field(..., description="Current value rendered as string")
    description: Optional[str] = Field(None, description="Human-readable description")
    restart_required: bool = Field(False, description="True when edits recommend a restart")


class SettingUpdateRequest(BaseModel):
    """Request payload for updating a general setting value."""

    value: str = Field(..., description="New value for the setting")


class ErrorResponse(BaseModel):
    """Standard error response model."""
    success: bool = Field(False, description="Always false for error responses")
    error: str = Field(..., description="Error type or category")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict] = Field(None, description="Additional error details")


#######################################################################
## Internal Data Models
#######################################################################

class WorkflowSummary(BaseModel):
    """Summary information about a workflow for internal use."""
    global_id: str
    name: str
    vault: str
    enabled: bool
    workflow_engine: str
    schedule_cron: Optional[str]
    description: str


class ConfigurationError(BaseModel):
    """Configuration error information for API responses."""
    vault: str
    workflow_name: Optional[str] = Field(None, description="Workflow name if determinable")
    file_path: str
    error_message: str
    error_type: str
    timestamp: datetime
