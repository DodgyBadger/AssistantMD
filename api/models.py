"""
Pydantic models for API request and response schemas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
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
    vault_name: Optional[str] = Field(
        None,
        description="Vault scope for system workflow templates.",
    )
    expect_failure: bool = Field(
        False,
        description="Validation/testing hint: marks execution failures as expected in workflow logs.",
    )


class WorkflowEnabledRequest(BaseModel):
    """Request model for changing workflow enabled state."""

    global_id: str = Field(..., description="Workflow global ID (vault/name or system/name format)")
    enabled: bool = Field(..., description="Desired enabled state")


class WorkflowEnabledResponse(BaseModel):
    """Response model for workflow enabled-state changes."""

    success: bool = Field(..., description="Whether the enabled state was updated")
    global_id: str = Field(..., description="Workflow global ID")
    enabled_before: bool = Field(..., description="Enabled state before the update")
    enabled_after: bool = Field(..., description="Enabled state after the update")
    message: str = Field(..., description="Human-readable update summary")


class WorkflowFileUpdateRequest(BaseModel):
    """Request model for replacing workflow source content."""

    content: str = Field(..., description="Complete workflow file content")
    expected_sha256: Optional[str] = Field(
        None,
        description="Optional hash from the last read response; rejects stale saves when provided.",
    )


class WorkflowFileResponse(BaseModel):
    """Response model for workflow source content."""

    global_id: str = Field(..., description="Workflow global ID")
    path: str = Field(..., description="Filesystem path for display")
    source: str = Field(..., description="Source scope: vault or system")
    content: str = Field(..., description="Complete workflow file content")
    sha256: str = Field(..., description="SHA-256 hash of the returned content")
    message: Optional[str] = Field(None, description="Human-readable update summary")


class ChatExecuteRequest(BaseModel):
    """Request model for chat execution."""
    vault_name: str = Field(..., description="Vault context for execution")
    prompt: str = Field(..., min_length=1, description="User prompt text")
    image_paths: List[str] = Field(
        default_factory=list,
        description="Optional image file paths (relative to vault or absolute within vault) to attach",
    )
    session_id: Optional[str] = Field(None, description="Session ID (generated if not provided)")
    tools: List[str] = Field(..., description="List of tool names to enable")
    model: str = Field(..., description="Model name to use")
    thinking: Optional[str] = Field(
        None,
        description="Optional per-request thinking override: default, on, off, minimal, low, medium, high, xhigh",
    )
    context_template: Optional[str] = Field(None, description="Optional context manager template name")
    workspace_path: Optional[str] = Field(None, description="Optional vault-relative workspace directory path")
    stream: bool = Field(False, description="Whether to stream the response (SSE format)")


#######################################################################
## Response Models
#######################################################################

class VaultInfo(BaseModel):
    """Information about a single vault."""
    name: str = Field(..., description="Vault name")
    path: str = Field(..., description="Full path to vault directory")
    workflow_count: int = Field(..., description="Number of workflows in this vault")
    workflows: List[str] = Field(default_factory=list, description="List of workflow names")
    tracked_files: Optional[int] = Field(None, description="Current files tracked by vault state")
    files_created_recent: Optional[int] = Field(None, description="Files created in the recent vault-state change window")
    files_deleted_recent: Optional[int] = Field(None, description="Files deleted in the recent vault-state change window")
    latest_vault_change_at: Optional[datetime] = Field(None, description="Latest vault-state change observation")


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
    default_model: Optional[str] = Field(None, description="Default model alias from settings")


class StatusResponse(BaseModel):
    """Response model for system status endpoint."""

    vaults: List[VaultInfo] = Field(default_factory=list, description="Information about discovered vaults")
    scheduler: SchedulerInfo = Field(..., description="Scheduler status information")
    system: SystemInfo = Field(..., description="System health information")
    total_vaults: int = Field(..., description="Total number of discovered vaults")
    total_workflows: int = Field(..., description="Total number of workflows across all vaults")
    enabled_workflows: List["WorkflowSummary"] = Field(default_factory=list, description="List of enabled workflows with details")
    disabled_workflows: List["WorkflowSummary"] = Field(default_factory=list, description="List of disabled workflows with details")
    system_workflow_templates: List["SystemWorkflowTemplateSummary"] = Field(
        default_factory=list,
        description="Packaged system workflow templates available to copy into a vault",
    )
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


class VaultTaskMutationInfo(BaseModel):
    """One recorded file mutation for a vault task."""

    id: int = Field(..., description="Mutation row id")
    task_id: str = Field(..., description="Execution task id that recorded this mutation")
    task_kind: Optional[str] = Field(None, description="Task kind such as chat or workflow")
    task_source: Optional[str] = Field(None, description="Task source such as api or scheduler")
    task_scope: Optional[str] = Field(None, description="Task scope")
    task_label: Optional[str] = Field(None, description="User-readable task label")
    goal_id: Optional[str] = Field(None, description="Optional goal_ops goal id associated with the mutation")
    step_id: Optional[str] = Field(None, description="Optional goal_ops step id associated with the mutation")
    path: str = Field(..., description="Vault-relative mutated path")
    related_path: Optional[str] = Field(None, description="Related vault-relative path for paired mutations")
    operation: str = Field(..., description="Mutation operation")
    event_sequence: Optional[int] = Field(None, description="Linked vault file event sequence")
    before_exists: bool = Field(..., description="Whether the file existed before mutation")
    before_hash: Optional[str] = Field(None, description="Content hash before mutation")
    before_snapshot_id: Optional[int] = Field(None, description="Retained pre-mutation file snapshot id")
    after_exists: bool = Field(..., description="Whether the file existed after mutation")
    after_hash: Optional[str] = Field(None, description="Content hash after mutation")
    after_snapshot_id: Optional[int] = Field(None, description="Retained post-mutation file snapshot id")
    snapshot_ref: Optional[str] = Field(None, description="Retained pre-mutation snapshot reference")
    created_at: datetime = Field(..., description="Mutation timestamp")
    expires_at: Optional[datetime] = Field(None, description="Snapshot retention expiration")


class VaultTaskMutationGroupInfo(BaseModel):
    """File mutations grouped by user-facing activity."""

    activity_id: str = Field(..., description="Activity group id")
    activity_kind: str = Field(..., description="Activity kind such as chat or workflow")
    activity_label: str = Field(..., description="User-facing activity label")
    chat_session_id: Optional[str] = Field(None, description="Chat session id for chat activity groups")
    chat_session_title: Optional[str] = Field(None, description="User-defined chat session title")
    chat_session_created_at: Optional[str] = Field(None, description="Chat session creation timestamp")
    chat_session_last_activity_at: Optional[str] = Field(None, description="Chat session last activity timestamp")
    task_id: str = Field(..., description="Primary task id or chat session scope for this group")
    task_kind: Optional[str] = Field(None, description="Task kind such as chat or workflow")
    task_source: Optional[str] = Field(None, description="Task source such as api or scheduler")
    task_scope: Optional[str] = Field(None, description="Task scope")
    task_label: Optional[str] = Field(None, description="User-readable task label")
    goal_id: Optional[str] = Field(None, description="Optional goal_ops goal id associated with the activity")
    step_id: Optional[str] = Field(None, description="Optional goal_ops step id associated with the activity")
    vault_id: str = Field(..., description="Stable vault id")
    vault_name: str = Field(..., description="Vault name at mutation time")
    mutation_count: int = Field(..., description="Number of returned mutations for the task")
    first_mutation_at: datetime = Field(..., description="First returned mutation timestamp")
    last_mutation_at: datetime = Field(..., description="Last returned mutation timestamp")
    expires_at: Optional[datetime] = Field(None, description="Earliest snapshot retention expiration")
    mutations: List[VaultTaskMutationInfo] = Field(default_factory=list, description="Returned mutations")


class VaultTaskMutationsResponse(BaseModel):
    """Response for recent vault file mutation activity."""

    vault_name: str = Field(..., description="Requested vault name")
    groups: List[VaultTaskMutationGroupInfo] = Field(
        default_factory=list,
        description="Recent task mutation groups",
    )


class VaultStateCleanupResponse(BaseModel):
    """Response for manual vault-state cleanup."""

    success: bool = Field(..., description="Whether cleanup completed")
    expired_mutation_rows_deleted: int = Field(..., description="Deleted expired mutation rows")
    expired_snapshot_rows_deleted: int = Field(..., description="Deleted expired snapshot rows")
    snapshot_files_deleted: int = Field(..., description="Deleted snapshot files")
    snapshot_dirs_deleted: int = Field(..., description="Deleted snapshot directories")
    message: str = Field(..., description="Human-readable cleanup summary")


class ExecuteWorkflowResponse(BaseModel):
    """Response model for starting manual workflow execution."""

    success: bool = Field(..., description="Whether workflow execution was started")
    global_id: str = Field(..., description="Workflow global ID that was started")
    status: str = Field(..., description="Current execution task status")
    task: "ExecutionTaskInfo" = Field(..., description="Execution task created for this workflow run")
    message: str = Field(..., description="Human-readable execution summary")


class ChatExecuteResponse(BaseModel):
    """Response model for chat execution."""
    response: str = Field(..., description="The AI's response")
    session_id: str = Field(..., description="Session identifier")
    message_count: int = Field(..., description="Total messages in conversation")


class ExecutionTaskInfo(BaseModel):
    """Process-local execution task snapshot."""

    task_id: str = Field(..., description="Execution task identifier")
    kind: str = Field(..., description="Task kind, such as chat or workflow")
    scope: str = Field(..., description="Task scope")
    source: str = Field(..., description="Task source, such as api, scheduler, tool, or system")
    label: str = Field(..., description="User-readable task label")
    status: str = Field(..., description="Task lifecycle status")
    created_at: datetime = Field(..., description="Task creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Task start timestamp")
    finished_at: Optional[datetime] = Field(None, description="Task terminal timestamp")
    cancel_requested: bool = Field(False, description="Whether cancellation has been requested")
    terminal_reason: Optional[str] = Field(None, description="Terminal reason when available")
    latest_event: Optional[str] = Field(None, description="Latest task lifecycle event")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Task metadata")


class ExecutionTaskListResponse(BaseModel):
    """Response model for execution task listing."""

    tasks: List[ExecutionTaskInfo] = Field(default_factory=list, description="Matching task snapshots")


class ExecutionTaskCancelResponse(BaseModel):
    """Response model for execution task cancellation."""

    task: ExecutionTaskInfo = Field(..., description="Task snapshot after cancellation request")
    cancelled: bool = Field(..., description="Whether the task was already or newly cancelled")




class ModelInfo(BaseModel):
    """Model metadata for UI configuration."""

    name: str = Field(..., description="User-friendly model name")
    provider: str = Field(..., description="Provider (anthropic, openai, google, etc.)")
    model_string: str = Field(..., description="Actual model identifier")
    capabilities: List[str] = Field(
        default_factory=lambda: ["text"],
        description="Declared model capabilities (e.g. text, vision)",
    )
    dimensions: Optional[int] = Field(
        None,
        description="Embedding vector dimensions when this is an embedding model alias",
    )
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
    chat_visible: bool = Field(True, description="Whether the tool should be exposed in chat metadata/UI")


class ProviderInfo(BaseModel):
    """Provider configuration metadata."""

    name: str = Field(..., description="Provider name")
    api_key: Optional[str] = Field(None, description="Secret name containing the API key, if required")
    base_url: Optional[str] = Field(None, description="Secret name or direct URL for custom endpoints")
    user_editable: bool = Field(False, description="If the provider entry can be edited via UI")
    api_key_has_value: bool = Field(False, description="True if the API key secret currently has a value")
    base_url_has_value: bool = Field(False, description="True if the base URL secret or literal value is set")
    configured_auth_mode: Optional[str] = Field(
        None,
        description="Configured provider auth mode when the provider supports auth modes.",
    )
    effective_auth_mode: Optional[str] = Field(
        None,
        description="Runtime auth mode after global overrides are applied.",
    )
    oauth_enabled: bool = Field(
        False,
        description="True when OpenAI OAuth behavior is globally enabled.",
    )
    oauth_status: Optional[str] = Field(
        None,
        description="Sanitized OAuth connection status for providers that support OAuth.",
    )
    oauth_disabled_reason: Optional[str] = Field(
        None,
        description="Reason OAuth is unavailable or ignored, when applicable.",
    )
    oauth_api_key_fallback_enabled: bool = Field(
        False,
        description="True when OAuth failures may explicitly fall back to API-key auth.",
    )
    oauth_api_key_fallback_available: bool = Field(
        False,
        description="True when an API-key fallback secret is configured.",
    )
    oauth_account_id: Optional[str] = Field(
        None,
        description="Sanitized connected OpenAI account identifier, when available.",
    )
    oauth_expires_at: Optional[str] = Field(
        None,
        description="OAuth token expiry timestamp, when available.",
    )
    oauth_last_refresh_at: Optional[str] = Field(
        None,
        description="Last successful OAuth refresh timestamp, when available.",
    )
    oauth_last_refresh_error: Optional[str] = Field(
        None,
        description="Sanitized OAuth refresh failure category or message.",
    )
    oauth_pending_expires_at: Optional[str] = Field(
        None,
        description="Pending OAuth connection expiry timestamp, when available.",
    )
    restart_required: bool = Field(
        False,
        description="True when recent edits require a full restart to take effect.",
    )


class MetadataResponse(BaseModel):
    """Unified metadata response for vaults, models, and tools."""
    vaults: List[str] = Field(..., description="Available vault names")
    models: List[ModelInfo] = Field(..., description="Available models")
    tools: List[ToolInfo] = Field(..., description="Available tools")
    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Selected settings values for UI hints.",
    )
    default_context_script: Optional[str] = Field(
        None,
        description="Default context script name for chat sessions.",
    )


class TemplateInfo(BaseModel):
    """Context template metadata for UI selection."""
    name: str = Field(..., description="Template filename")
    source: str = Field(..., description="Template source: vault or system")
    path: Optional[str] = Field(None, description="Full path to template, if available")


class ChatWorkspaceInfo(BaseModel):
    """Vault-relative workspace directory associated with a chat session."""

    path: str = Field("", description="Vault-relative workspace directory path")
    exists: bool = Field(False, description="Whether a workspace path is set")


class ChatSessionInfo(BaseModel):
    """Persisted chat session summary for UI selection."""

    session_id: str = Field(..., description="Session identifier")
    created_at: str = Field(..., description="Session creation timestamp")
    last_activity_at: str = Field(..., description="Most recent activity timestamp")
    title: Optional[str] = Field(None, description="User-defined title, if set")
    workspace: Optional[ChatWorkspaceInfo] = Field(None, description="Workspace associated with this session")
    has_summary: bool = Field(False, description="Whether a session summary record exists")


class ChatSessionWorkspaceRequest(BaseModel):
    """Request to set or clear a chat session workspace."""

    vault_name: str = Field(..., description="Owning vault name")
    path: Optional[str] = Field(None, description="Vault-relative workspace directory path")


class ChatSessionForkRequest(BaseModel):
    """Request to fork one persisted chat session."""

    vault_name: str = Field(..., description="Owning vault name")
    through_sequence_index: int = Field(
        ...,
        ge=0,
        description="Persisted message sequence index to fork through, inclusive",
    )


class ChatSessionForkResponse(BaseModel):
    """Response returned after creating a forked chat session."""

    session: ChatSessionInfo = Field(..., description="New forked session summary")
    source_session_id: str = Field(..., description="Source session identifier")
    through_sequence_index: int = Field(..., description="Inclusive source message sequence fork point")
    copied_message_count: int = Field(..., description="Number of messages copied into the fork")


class ChatSessionSummaryResponse(BaseModel):
    """Lightweight session summary payload for UI previews."""

    session_id: str = Field(..., description="Session identifier")
    vault_name: str = Field(..., description="Owning vault name")
    has_summary: bool = Field(..., description="Whether a session summary record exists")
    summary: Optional[str] = Field(None, description="Extracted session summary")
    user_intent: Optional[str] = Field(None, description="Extracted user intent")
    created_at: Optional[str] = Field(None, description="Session summary creation timestamp")
    updated_at: Optional[str] = Field(None, description="Session summary update timestamp")
    domain: Optional[str] = Field(None, description="Extracted domain")
    work_product: Optional[str] = Field(None, description="Extracted work product")
    workspace_path: Optional[str] = Field(None, description="Workspace path stored for this session summary")
    named_entities: Optional[str] = Field(None, description="Extracted named entities")
    source_summary: Optional[str] = Field(None, description="Extracted source summary")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Summary metadata")
    artifacts: List[Dict[str, Any]] = Field(default_factory=list, description="Linked summary artifacts")
    vector_index: Dict[str, Any] = Field(default_factory=dict, description="Vector index coverage")


class ChatSessionSummaryUpdateRequest(BaseModel):
    """Request to manually update a session summary record."""

    summary: Optional[str] = Field(None, description="Replacement summary")
    domain: Optional[str] = Field(None, description="Replacement domain")
    work_product: Optional[str] = Field(None, description="Replacement work product")
    user_intent: Optional[str] = Field(None, description="Replacement user intent")
    workspace_path: Optional[str] = Field(None, description="Replacement workspace path")
    named_entities: Optional[str] = Field(None, description="Replacement named entities")
    source_summary: Optional[str] = Field(None, description="Replacement source summary")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Replacement summary metadata")


class ChatSessionTitleRequest(BaseModel):
    """Request to set or clear the user-defined title for a session."""

    vault_name: str = Field(..., description="Owning vault name")
    title: Optional[str] = Field(None, description="New title; null or empty clears it")


class ChatSessionExportRequest(BaseModel):
    """Request to export one persisted chat session as markdown."""

    vault_name: str = Field(..., description="Owning vault name")


class ChatSessionMessageInfo(BaseModel):
    """Persisted normalized chat message for session rehydration."""

    sequence_index: int = Field(..., description="Stable sequence index within the session")
    fork_sequence_index: Optional[int] = Field(
        None,
        description="Effective inclusive message sequence to use when forking from this rendered message",
    )
    role: str = Field(..., description="Normalized role for rendering")
    content: str = Field(..., description="Normalized rendered message content")
    message_type: str = Field(..., description="Provider-native message class name")
    direction: str = Field(..., description="Request/response direction for the provider-native message")
    is_tool_message: bool = Field(False, description="Whether this row represents a tool call/return message")
    tool_call_ids: List[str] = Field(default_factory=list, description="Tool calls declared by this message")
    tool_return_ids: List[str] = Field(default_factory=list, description="Tool returns declared by this message")


class ChatSessionToolEventInfo(BaseModel):
    """Persisted structured tool event for UI rehydration."""

    tool_call_id: str = Field(..., description="Tool call identifier")
    tool_name: str = Field(..., description="Tool name")
    event_type: str = Field(..., description="Event type such as call, result, or overflow_cached")
    created_at: str = Field(..., description="Event timestamp")
    args: Optional[Dict[str, Any]] = Field(None, description="Tool arguments when captured")
    result_text: Optional[str] = Field(None, description="Tool result text or summary")
    result_metadata: Dict[str, Any] = Field(default_factory=dict, description="Structured tool result metadata")
    artifact_ref: Optional[str] = Field(None, description="Cache/artifact reference when present")


class ChatSessionFailureInfo(BaseModel):
    """Internal recovery marker for an accepted chat turn that did not complete."""

    status: str = Field(..., description="Failure marker status")
    phase: str = Field(..., description="Execution phase where the turn failed")
    streaming: bool = Field(..., description="Whether the failed turn was streaming")
    error_type: str = Field(..., description="Stable exception type")
    error: str = Field("", description="Concise failure message")
    failure_kind: str = Field("", description="Stable failure category")
    retryable: bool = Field(False, description="Whether retrying the same request may succeed")
    http_status: Optional[int] = Field(None, description="Provider HTTP status when available")
    retry_after: Optional[str] = Field(None, description="Provider retry-after hint when available")
    model: Optional[str] = Field(None, description="Model selected for the failed turn")
    tools: List[str] = Field(default_factory=list, description="Tools selected for the failed turn")
    accepted_user_sequence_index: int = Field(..., description="Accepted user message sequence index")
    recorded_at: str = Field(..., description="Marker timestamp")
    suggested_action: str = Field("", description="Agent-safe recovery guidance")


class ChatSessionDetailResponse(BaseModel):
    """Persisted chat session payload for client-side rehydration."""

    session_id: str = Field(..., description="Session identifier")
    vault_name: str = Field(..., description="Owning vault name")
    workspace: Optional[ChatWorkspaceInfo] = Field(None, description="Workspace associated with this session")
    latest_failure: Optional[ChatSessionFailureInfo] = Field(None, description="Latest unfinished-turn marker")
    messages: List[ChatSessionMessageInfo] = Field(default_factory=list, description="Persisted messages")
    tool_events: List[ChatSessionToolEventInfo] = Field(default_factory=list, description="Persisted tool events")


class VaultDirectoryInfo(BaseModel):
    """One child directory in a vault directory listing."""

    name: str = Field(..., description="Directory basename")
    path: str = Field(..., description="Vault-relative directory path")
    has_children: bool = Field(False, description="Whether this directory has child directories")


class VaultDirectoryListResponse(BaseModel):
    """Directory listing response for workspace selection."""

    path: str = Field("", description="Listed vault-relative directory path")
    directories: List[VaultDirectoryInfo] = Field(default_factory=list, description="Child directories")


class ChatSessionsPurgeRequest(BaseModel):
    """Request to purge old chat sessions for a vault."""

    vault_name: str = Field(..., description="Vault to purge sessions from")
    older_than_days: Optional[int] = Field(None, description="Delete sessions older than this many days; null deletes all")


class ChatSessionsPurgeResponse(BaseModel):
    """Result of a chat session purge operation."""

    deleted: int = Field(..., description="Number of sessions deleted")
    message: str = Field(..., description="Human-readable summary")


class GoalCleanupRequest(BaseModel):
    """Request to remove old completed or cancelled goals for a vault."""

    vault_name: str = Field(..., description="Vault to clean goals from")
    status: str = Field(
        "completed",
        description='Goal status filter: "completed", "cancelled", or "completed_or_cancelled"',
    )
    older_than_days: Optional[int] = Field(None, description="Delete goals older than this many days; null deletes all matches")


class GoalCleanupResponse(BaseModel):
    """Result of a goal cleanup operation."""

    success: bool = Field(True, description="Whether cleanup completed successfully")
    deleted: int = Field(..., description="Number of goals deleted")
    message: str = Field(..., description="Human-readable summary")


class ChatSessionExportResponse(BaseModel):
    """Result of exporting one chat session transcript."""

    session_id: str = Field(..., description="Session identifier")
    filename: str = Field(..., description="Transcript filename created for the export")
    path: str = Field(..., description="Absolute transcript path in the vault")


class ChatHistoryCompactionRequest(BaseModel):
    """Request to compact one persisted chat session."""

    vault_name: str = Field(..., description="Owning vault name")
    focus: Optional[str] = Field(None, description="Optional summary focus instructions")


class ChatHistoryCompactionStatusResponse(BaseModel):
    """Estimated compaction status for one chat session."""

    session_id: str = Field(..., description="Session identifier")
    vault_name: str = Field(..., description="Owning vault name")
    compaction_type: str = Field(..., description="Configured compaction policy")
    messages_before: int = Field(..., description="Current stored message count")
    estimated_tokens_before: int = Field(..., description="Estimated current history tokens")
    compaction_token_threshold: int = Field(..., description="Configured compaction threshold")
    compaction_keep_recent: int = Field(..., description="Target recent message count to keep")
    recommended: bool = Field(..., description="Whether compaction is currently recommended")
    already_compacted: bool = Field(..., description="Whether this session has prior compaction metadata")


class ChatHistoryCompactionResponse(BaseModel):
    """Result of compacting one chat session."""

    session_id: str = Field(..., description="Session identifier")
    vault_name: str = Field(..., description="Owning vault name")
    status: str = Field(..., description="Compaction status")
    messages_before: int = Field(..., description="Message count before compaction")
    messages_after: int = Field(..., description="Message count after compaction")
    estimated_tokens_before: int = Field(..., description="Estimated tokens before compaction")
    estimated_tokens_after: int = Field(..., description="Estimated tokens after compaction")
    kept_recent: int = Field(..., description="Recent raw messages preserved verbatim")
    summary_message_index: int = Field(..., description="Stored summary message index")
    compaction_id: str = Field(..., description="Compaction audit identifier")
    compacted_at: str = Field(..., description="Compaction timestamp")
    source: str = Field(..., description="Compaction source")


class ModelConfigRequest(BaseModel):
    """Payload for creating or updating a model mapping."""

    provider: str = Field(..., description="Provider name the model uses")
    model_string: str = Field(..., description="Provider-specific model identifier")
    capabilities: Optional[List[str]] = Field(
        None,
        description="Optional model capabilities list (e.g. [\"text\", \"vision\"] or [\"embedding\"])",
    )
    dimensions: Optional[int] = Field(
        None,
        description="Embedding vector dimensions for embedding-capable model aliases",
    )
    description: Optional[str] = Field(None, description="Optional description for UI display")


class ProviderConfigRequest(BaseModel):
    """Payload for creating or updating a provider configuration."""

    api_key: Optional[str] = Field(None, description="Secret name containing the provider API key")
    base_url: Optional[str] = Field(None, description="Either a direct URL or the name of a stored secret")
    auth_mode: Optional[Literal["api_key", "oauth"]] = Field(
        None,
        description="OpenAI auth mode; only supported for the built-in openai provider",
    )
    oauth_api_key_fallback_enabled: Optional[bool] = Field(
        None,
        description="Allow OpenAI OAuth failures to fall back to API-key auth",
    )
    api_key_value: Optional[str] = Field(None, description="Optional API key value to persist in the secrets store")
    base_url_value: Optional[str] = Field(None, description="Optional base URL value to persist in the secrets store")


class OpenAIOAuthStartRequest(BaseModel):
    """Payload for starting an OpenAI OAuth connection."""

    redirect_uri: Optional[str] = Field(
        None,
        description="Optional callback URI; defaults to the API callback endpoint",
    )


class OpenAIOAuthStartResponse(BaseModel):
    """Bootstrap response for an OpenAI OAuth connection attempt."""

    auth_url: str = Field(..., description="Authorization URL to open in a browser")
    state: str = Field(..., description="Opaque OAuth state for this connection attempt")
    redirect_uri: str = Field(..., description="Callback URI bound to this attempt")
    expires_at: str = Field(..., description="Pending connection expiry timestamp")


class OpenAIOAuthCompleteRequest(BaseModel):
    """Payload for completing OpenAI OAuth manually."""

    redirect_url: Optional[str] = Field(
        None,
        description="Full pasted redirect URL containing code and state",
    )
    code: Optional[str] = Field(None, description="Authorization code")
    state: Optional[str] = Field(None, description="OAuth state")


class OperationResult(BaseModel):
    """Generic success response for configuration operations."""

    success: bool = Field(True, description="Whether the operation succeeded")
    message: str = Field(..., description="Human-readable summary")
    restart_required: bool = Field(
        False,
        description="True when a full restart is still required for secret changes.",
    )


class CachePurgeResponse(BaseModel):
    """Response model for manual cache maintenance operations."""

    success: bool = Field(True, description="Whether the purge completed successfully")
    message: str = Field(..., description="Human-readable purge summary")
    purged_count: int = Field(..., description="Number of expired cache artifacts removed")


class SystemTemplateSeedResponse(BaseModel):
    """Response model for manual system authoring template refresh."""

    success: bool = Field(..., description="Whether the refresh completed without copy errors")
    message: str = Field(..., description="Human-readable refresh summary")
    created: List[str] = Field(default_factory=list, description="System template files created")
    updated: List[str] = Field(default_factory=list, description="System template files overwritten")
    skipped: List[str] = Field(default_factory=list, description="System template files left unchanged")
    errors: List[str] = Field(default_factory=list, description="Copy errors encountered during refresh")


class SystemMigrationTargetInfo(BaseModel):
    """Migration status for one managed system database."""

    db_name: str = Field(..., description="System database name")
    namespace: str = Field(..., description="Migration namespace tracked inside the database")
    db_path: str = Field(..., description="Filesystem path to the database")
    exists: bool = Field(..., description="Whether the database file currently exists")
    applied_versions: List[int] = Field(default_factory=list, description="Applied migration versions")
    pending_versions: List[int] = Field(default_factory=list, description="Pending migration versions")
    backup_path: Optional[str] = Field(None, description="Backup created during the latest migration run")


class SystemMigrationStatusResponse(BaseModel):
    """Response containing system database migration status."""

    success: bool = Field(True, description="Whether the status request completed successfully")
    message: str = Field(..., description="Human-readable migration status summary")
    system_root: str = Field(..., description="Filesystem path to the active system directory")
    pending_count: int = Field(..., description="Total pending migration versions")
    targets: List[SystemMigrationTargetInfo] = Field(default_factory=list)


class SystemMigrationRunRequest(BaseModel):
    """Request payload for running system database migrations."""

    backup: bool = Field(True, description="Create timestamped backups before applying pending migrations")


class SystemMigrationRunResponse(SystemMigrationStatusResponse):
    """Response containing final status after running system database migrations."""

    backups_created: List[str] = Field(default_factory=list, description="Backup files created during the run")


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
    category: Optional[str] = Field(None, description="Settings UI grouping label")
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


class WorkflowLoadErrorsResponse(BaseModel):
    """Structured workflow load errors for authoring and repair loops."""

    errors: List["ConfigurationError"] = Field(
        default_factory=list,
        description="Workflow configuration errors discovered during loading",
    )


#######################################################################
## Internal Data Models
#######################################################################

class WorkflowSummary(BaseModel):
    """Summary information about a workflow for internal use."""
    global_id: str
    name: str
    vault: str
    enabled: bool
    run_type: str
    schedule_cron: Optional[str]
    description: str


class SystemWorkflowTemplateSummary(BaseModel):
    """Summary information about a packaged system workflow template."""

    name: str
    run_type: str
    enabled: bool
    schedule_cron: Optional[str]
    description: str
    path: str


class ConfigurationError(BaseModel):
    """Configuration error information for API responses."""
    vault: str
    workflow_name: Optional[str] = Field(None, description="Workflow name if determinable")
    file_path: str
    error_message: str
    error_type: str
    timestamp: datetime
