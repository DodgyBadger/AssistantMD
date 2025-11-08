"""
Runtime configuration reload helpers.

Provides a single entry point for refreshing configuration caches after
users edit settings or environment variables through the API.
"""

from dataclasses import dataclass
from datetime import datetime

from core.settings import (
    ConfigurationStatus,
    get_configuration_status,
    refresh_app_settings_cache,
    refresh_configuration_status_cache,
)
from core.llm.model_utils import refresh_model_cache
from core.logger import refresh_logfire_configuration
from core.runtime.state import get_runtime_context, has_runtime_context
from core.settings.store import refresh_settings_cache


@dataclass
class ConfigurationReloadResult:
    """Outcome from executing a configuration reload."""

    performed_at: datetime
    status: ConfigurationStatus
    restart_required: bool = False


def reload_configuration(restart_required: bool = False) -> ConfigurationReloadResult:
    """
    Refresh configuration caches and update runtime metadata.

    Args:
        restart_required: Propagated flag indicating the caller wants to surface
            a restart recommendation (for example, after editing a setting that
            cannot be hot-reloaded).

    Returns:
        ConfigurationReloadResult summarising the new configuration status.
    """
    refresh_settings_cache()
    refresh_model_cache()

    refresh_app_settings_cache()
    refresh_configuration_status_cache()
    refresh_logfire_configuration(force=True)
    status = get_configuration_status()

    performed_at = datetime.now()

    if has_runtime_context():
        runtime = get_runtime_context()
        runtime.last_config_reload = performed_at

    return ConfigurationReloadResult(
        performed_at=performed_at,
        status=status,
        restart_required=restart_required,
    )
