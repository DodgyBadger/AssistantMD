"""
Service layer for API operations.
Handles business logic for status reporting, vault management, etc.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import yaml

from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context, RuntimeStateError
from core.scheduling.jobs import setup_scheduler_jobs, create_job_args
from core.settings.store import (
    get_models_config,
    get_tools_config,
    get_providers_config,
    get_active_settings_path,
)
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
from core.llm.session_manager import SessionManager
from core.llm.chat_executor import execute_chat_prompt
from core.constants import (
    COMPACT_SUMMARY_PROMPT,
    COMPACT_INSTRUCTIONS,
    WORKFLOW_CREATION_SUMMARY_PROMPT,
    SYSTEM_DATA_ROOT,
)
from .utils import generate_session_id
from .models import (
    VaultInfo,
    SchedulerInfo,
    SystemInfo,
    StatusResponse,
    WorkflowSummary,
    ConfigurationError as APIConfigurationError,
    ModelInfo,
    ToolInfo,
    ChatMetadataResponse,
    ConfigurationStatusInfo,
    ConfigurationIssueInfo,
    ProviderInfo,
    ModelConfigRequest,
    ProviderConfigRequest,
    OperationResult,
    SecretInfo,
    SecretUpdateRequest,
    SettingInfo,
    SettingUpdateRequest,
    SystemLogResponse,
    SystemSettingsResponse,
)
from .exceptions import SystemConfigurationError

# Create API services logger
logger = UnifiedLogger(tag="api-services")

# Global variable to track system startup time
_system_startup_time: Optional[datetime] = None


def _get_workflow_loader():
    """Get workflow loader from runtime context."""
    runtime = get_runtime_context()
    return runtime.workflow_loader


def set_system_startup_time(startup_time: datetime):
    """Set the system startup time for status reporting."""
    global _system_startup_time
    _system_startup_time = startup_time


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

        # Create VaultInfo objects from cached data
        vault_infos = []
        for vault_name, data in vault_data.items():
            vault_info = VaultInfo(
                name=vault_name,
                path=data['path'],
                workflow_count=len(data['workflows']),
                workflows=data['workflows']
            )
            vault_infos.append(vault_info)

        return vault_infos

    except Exception as e:
        error_msg = f"Failed to collect vault status: {str(e)}"
        raise SystemConfigurationError(error_msg) from e


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
            job_summary = {
                'id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time,
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

    except Exception:
        # Return safe defaults on error
        return SchedulerInfo(
            running=False,
            total_jobs=0,
            enabled_workflows=0,
            disabled_workflows=0,
            job_details=[]
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

        scheduler_info.enabled_workflows = len(enabled_workflows)
        scheduler_info.disabled_workflows = len(disabled_workflows)

        # Get configuration errors and overall configuration health
        configuration_errors = get_configuration_errors()
        configuration_status_snapshot = validate_settings()
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
        )

        status_response = StatusResponse(
            vaults=vaults,
            scheduler=scheduler_info,
            system=system_info,
            total_vaults=total_vaults,
            total_workflows=total_workflows,
            enabled_workflows=enabled_workflows,
            disabled_workflows=disabled_workflows,
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
        summary = WorkflowSummary(
            global_id=workflow.global_id,
            name=workflow.name,
            vault=workflow.vault,
            enabled=workflow.enabled,
            workflow_engine=workflow.workflow_name,
            schedule_cron=workflow.schedule_string,
            description=workflow.description
        )
        summaries.append(summary)

    return summaries


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
        # Get scheduler if not provided
        if scheduler is None:
            try:
                runtime = get_runtime_context()
                scheduler = runtime.scheduler
            except RuntimeStateError:
                scheduler = None
        
        # Use the shared scheduler utilities for the rescan
        results = await setup_scheduler_jobs(scheduler, manual_reload=True)
        
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
    log_path = Path(SYSTEM_DATA_ROOT) / "activity.log"

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

    return _build_settings_response(path)


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
        user_editable = getattr(config, "user_editable", True)
        description = getattr(config, "description", None)
    else:
        provider = config['provider']
        model_string = config['model_string']
        user_editable = config.get('user_editable', True)
        description = config.get('description')

    status_message = None
    if issue_messages:
        status_message = issue_messages.get(name)

    return ModelInfo(
        name=name,
        provider=provider,
        model_string=model_string,
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

    return _build_model_info(model_name, updated, config_status.model_availability, issue_messages)


def delete_configurable_model(model_name: str) -> OperationResult:
    """Remove a model mapping if permitted."""
    try:
        delete_model_mapping(model_name)
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration()
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

    if payload.api_key_value is not None:
        key_value = (payload.api_key_value or "").strip()
        if key_value:
            if not api_key:
                api_key = _derive_secret_name(provider_name, "API_KEY")
            set_secret_value(api_key, key_value)
        else:
            target = api_key or existing_api_key
            if target and "://" not in target:
                remove_secret(target)
            api_key = None

    if payload.base_url_value is not None:
        url_value = (payload.base_url_value or "").strip()
        if url_value:
            if not base_url or "://" in base_url:
                base_url = _derive_secret_name(provider_name, "BASE_URL")
            set_secret_value(base_url, url_value)
        else:
            target = base_url or existing_base_url
            if target and "://" not in target:
                remove_secret(target)
            base_url = None

    try:
        updated = upsert_provider_config(
            name=provider_name,
            api_key=api_key,
            base_url=base_url,
        )
    except SettingsError as exc:
        raise SystemConfigurationError(str(exc)) from exc

    reload_result = reload_configuration()

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

    return OperationResult(
        success=True,
        message=f"Deleted {name}.",
        restart_required=reload_result.restart_required,
    )


async def execute_workflow_manually(global_id: str, step_name: str = None) -> Dict[str, Any]:
    """
    Execute a specific workflow manually.
    
    Args:
        global_id: Workflow global ID in format "vault/name"
        step_name: If provided, execute only the specified step (e.g. 'STEP1')
        
    Returns:
        Dictionary with execution results and timing information
        
    Raises:
        SystemConfigurationError: If workflow not found or execution fails
        ValueError: If global_id format is invalid or step_name not found
    """
    try:
        # Validate global_id format
        if '/' not in global_id:
            raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")
        
        loaded_workflows = await _get_workflow_loader().load_workflows(
            force_reload=True, target_global_id=global_id
        )

        if not loaded_workflows:
            raise ValueError(f"Workflow not found: {global_id}")

        target_workflow = loaded_workflows[0]

        await _get_workflow_loader().ensure_workflow_directories(target_workflow)

        workflow_function = target_workflow.workflow_function
        
        # Execute workflow with timing using job arguments
        start_time = datetime.now()
        try:
            # Create job arguments
            job_args = create_job_args(target_workflow.global_id)

            # Execute workflow with job arguments and optional step_name
            kwargs = {}
            if step_name is not None:
                kwargs['step_name'] = step_name
            await workflow_function(job_args, **kwargs)
            execution_time = (datetime.now() - start_time).total_seconds()
            
        except Exception as workflow_error:
            execution_time = (datetime.now() - start_time).total_seconds()
            # Re-raise as SystemConfigurationError for API layer
            raise SystemConfigurationError(f"Workflow execution failed for '{global_id}': {str(workflow_error)}")
        
        # Prepare results
        results = {
            'success': True,
            'global_id': global_id,
            'execution_time_seconds': execution_time,
            'output_files': [],  # TODO: Enhanced in Phase 4
            'message': f"Workflow '{global_id}' executed successfully in {execution_time:.2f} seconds"
        }
        
        return results
        
    except (ValueError, SystemConfigurationError):
        raise  # Re-raise known errors
    except Exception as e:
        error_msg = f"Failed to execute workflow '{global_id}': {str(e)}"
        raise SystemConfigurationError(error_msg) from e


async def get_chat_metadata() -> ChatMetadataResponse:
    """
    Get metadata for chat UI configuration.

    Returns available vaults, models, and tools dynamically from
    runtime context and settings.yaml.

    Returns:
        ChatMetadataResponse with vaults, models, and tools
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
            user_editable = getattr(config, "user_editable", True)
            description = getattr(config, "description", None)
        else:
            provider = config['provider']
            model_string = config['model_string']
            user_editable = config.get('user_editable', True)
            description = config.get('description')

        models.append(
            ModelInfo(
                name=name,
                provider=provider,
                model_string=model_string,
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
        else:
            description = config.get('description', '')
            requires_secrets = list(config.get('requires_secrets') or config.get('requires_env') or [])
            user_editable = config.get('user_editable', False)

        tools.append(
            ToolInfo(
                name=name,
                description=description,
                requires_secrets=requires_secrets,
                available=config_status.tool_availability.get(name, True),
                user_editable=user_editable,
            )
        )

    return ChatMetadataResponse(
        vaults=vaults,
        models=models,
        tools=tools
    )


async def compact_conversation_history(
    session_id: str,
    vault_name: str,
    model: str,
    user_instructions: Optional[str],
    session_manager: SessionManager,
    vault_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compact conversation history by generating LLM summary in the current session,
    then creating a new session starting with that summary.

    Flow:
    1. Send summarization prompt to current session (added to history)
    2. Get summary response from LLM
    3. Generate new session_id
    4. Initialize new session with summary as first message
    5. Return new session_id for UI to update

    Args:
        session_id: Current session to compact
        vault_name: Vault context
        model: Model name to use for summarization
        user_instructions: Optional user guidance for what to prioritize
        session_manager: SessionManager instance
        vault_path: Path to vault directory (optional, resolved from runtime if not provided)

    Returns:
        Dict with summary, original_count, compacted_count, and new_session_id

    Raises:
        ValueError: If history is too short to compact or session not found
    """
    history = session_manager.get_history(session_id, vault_name)

    if not history or len(history) <= 2:
        raise ValueError("History too short to compact (need more than 2 messages)")

    original_count = len(history)

    # Build summarization prompt
    summarize_prompt = COMPACT_SUMMARY_PROMPT

    if user_instructions:
        summarize_prompt += f"\n\nUser guidance: {user_instructions}"

    # Build instructions for the summarization agent
    summarize_instructions = COMPACT_INSTRUCTIONS

    # Get vault path from runtime context if not provided
    if vault_path is None:
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / vault_name)

    # Execute summarization in the SAME session (gets added to history like any other turn)
    result = await execute_chat_prompt(
        vault_name=vault_name,
        vault_path=vault_path,
        prompt=summarize_prompt,
        session_id=session_id,  # Same session, not temp
        tools=[],  # No tools needed for summarization
        model=model,
        use_conversation_history=True,
        session_manager=session_manager,
        instructions=summarize_instructions
    )

    summary = result.response

    # Generate new session_id for fresh conversation
    new_session_id = generate_session_id(vault_name)

    # Get the summary message from current session (last assistant message)
    current_history = session_manager.get_history(session_id, vault_name)
    if current_history:
        summary_message = current_history[-1]  # Last message is the summary

        # Initialize new session with just the summary
        session_manager.add_messages(new_session_id, vault_name, [summary_message])

    return {
        "summary": summary,
        "original_count": original_count,
        "compacted_count": 1,
        "new_session_id": new_session_id
    }


async def start_workflow_creation(
    session_id: str,
    vault_name: str,
    model: str,
    user_instructions: Optional[str],
    session_manager: SessionManager,
    vault_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Start workflow creation conversation from current chat session or fresh.

    Handles two scenarios:
    1. Existing conversation: Summarizes with creation focus, starts new session
    2. No/minimal conversation: Skips summary, starts fresh creation session

    The new session uses workflow creation instructions so the LLM gathers
    requirements and writes the workflow file using available tools.

    Args:
        session_id: Current session to summarize (may be empty/minimal)
        vault_name: Vault context for workflow creation
        model: Model name to use for creation conversation
        user_instructions: Optional user guidance for workflow requirements
        session_manager: SessionManager instance
        vault_path: Path to vault directory (optional, resolved from runtime if not provided)

    Returns:
        Dict with summary, original_count, compacted_count, and new_session_id
    """
    history = session_manager.get_history(session_id, vault_name)

    # Get vault path from runtime context if not provided
    if vault_path is None:
        runtime = get_runtime_context()
        vault_path = str(runtime.config.data_root / vault_name)

    # Check if we have existing conversation to summarize
    has_history = history and len(history) > 2

    if has_history:
        # Scenario 1: Existing conversation - summarize with creation focus
        original_count = len(history)

        summarize_prompt = WORKFLOW_CREATION_SUMMARY_PROMPT
        if user_instructions:
            summarize_prompt += f"\n\nUser's requirements: {user_instructions}"

        # Execute summarization in SAME session (gets added to history)
        result = await execute_chat_prompt(
            vault_name=vault_name,
            vault_path=vault_path,
            prompt=summarize_prompt,
            session_id=session_id,
            tools=[],
            model=model,
            use_conversation_history=True,
            session_manager=session_manager,
            instructions="Summarize focusing on automation opportunities and workflow design."
        )

        summary = result.response

        # Generate new session_id for creation conversation
        new_session_id = generate_session_id(vault_name)

        # Get summary message from current session (last assistant message)
        current_history = session_manager.get_history(session_id, vault_name)
        if current_history:
            summary_message = current_history[-1]
            # Initialize new session with summary
            session_manager.add_messages(new_session_id, vault_name, [summary_message])
    else:
        # Scenario 2: No/minimal conversation - start fresh
        original_count = len(history) if history else 0
        summary = "Starting fresh workflow creation conversation."

        # Generate new session_id for creation conversation
        new_session_id = generate_session_id(vault_name)

        # No summary to add - new session starts empty, will use creation instructions

    return {
        "summary": summary,
        "original_count": original_count,
        "compacted_count": 1 if has_history else 0,
        "new_session_id": new_session_id
    }
