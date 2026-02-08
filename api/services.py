"""
Service layer for API operations.
Handles business logic for status reporting, vault management, etc.
"""

import json
import re
import shutil
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
from .models import (
    VaultInfo,
    SchedulerInfo,
    SystemInfo,
    StatusResponse,
    WorkflowSummary,
    ConfigurationError as APIConfigurationError,
    ModelInfo,
    ToolInfo,
    MetadataResponse,
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
    TemplateInfo,
)
from .exceptions import SystemConfigurationError
from core.constants import ASSISTANTMD_ROOT_DIR, IMPORT_DIR
from core.ingestion.models import SourceKind, JobStatus
import os
from core.ingestion.service import IngestionService
from core.ingestion.registry import importer_registry
from core.ingestion.jobs import find_job_for_source
from core.context.templates import list_templates

# Create API services logger
logger = UnifiedLogger(tag="api-services")

# Global variable to track system startup time
_system_startup_time: Optional[datetime] = None


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


def scan_import_folder(
    vault: str,
    queue_only: bool = False,
    strategies: list[str] | None = None,
):
    """
    Enqueue ingestion jobs for files in AssistantMD/Import for a vault.
    """
    runtime = get_runtime_context()
    import_root = Path(runtime.config.data_root) / vault / ASSISTANTMD_ROOT_DIR / IMPORT_DIR
    legacy_import_root = Path(runtime.config.data_root) / vault / ASSISTANTMD_ROOT_DIR / "import"
    import_root.mkdir(parents=True, exist_ok=True)

    ingest_service: IngestionService = runtime.ingestion

    jobs_created = []
    skipped = []
    # Registry-backed filter for supported types
    supported_exts = {key for key in importer_registry.keys() if key.startswith(".")}

    search_roots = [import_root]
    if legacy_import_root.exists():
        search_roots.append(legacy_import_root)

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

            job = ingest_service.enqueue_job(
                source_uri=item.name,
                vault=vault,
                source_type=SourceKind.FILE.value,
                mime_hint=None,
                options={"strategies": strategies} if strategies else {},
            )
            jobs_created.append(job)

    # If not queuing, process immediately for fast-path UX
    if not queue_only and jobs_created:
        refreshed_jobs = []
        for job in jobs_created:
            try:
                ingest_service.process_job(job.id)
            except Exception:
                # process_job updates status/error; continue to next job
                pass
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


def import_url_direct(vault: str, url: str, clean_html: bool = True):
    """
    Synchronously import a single URL and return the job record after processing.
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
    try:
        ingest_service.process_job(job.id)
    except Exception:
        # process_job records failure status; propagate via job state
        pass
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
        
        logger.info(
            "Workflow execution started",
            data={
                "global_id": global_id,
                "step_name": step_name,
            },
        )

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
        logger.info(
            "Workflow execution finished",
            data={
                "global_id": global_id,
                "execution_time_seconds": execution_time,
            },
        )
        
        return results
        
    except (ValueError, SystemConfigurationError):
        raise  # Re-raise known errors
    except Exception as e:
        error_msg = f"Failed to execute workflow '{global_id}': {str(e)}"
        raise SystemConfigurationError(error_msg) from e


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

    default_context_template = None
    try:
        default_entry = get_general_settings().get("default_context_template")
        if default_entry and default_entry.value:
            default_context_template = str(default_entry.value).strip() or None
    except Exception:
        default_context_template = None

    return MetadataResponse(
        vaults=vaults,
        models=models,
        tools=tools,
        settings={
            "auto_buffer_max_tokens": getattr(
                get_general_settings().get("auto_buffer_max_tokens"), "value", 0
            )
        },
        default_context_template=default_context_template,
    )
