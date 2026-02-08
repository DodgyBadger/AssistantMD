"""
Application settings and configuration health utilities.

Provides a single typed interface for environment-driven settings along with
helpers to diagnose missing configuration required for runtime features.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.settings.store import (
    ModelConfig,
    ProviderConfig,
    ToolConfig,
    SETTINGS_TEMPLATE,
    get_general_settings,
    get_models_config,
    get_providers_config,
    get_tools_config,
)
from core.settings.secrets_store import load_secrets, secret_has_value


class SettingsError(Exception):
    """Raised when application settings are invalid or unavailable."""


class ConfigurationIssue(BaseModel):
    """Represents a configuration validation issue."""

    name: str
    message: str
    severity: str  # 'error' or 'warning'


class ConfigurationStatus(BaseModel):
    """Aggregated configuration validation results."""

    issues: List[ConfigurationIssue] = Field(default_factory=list)
    tool_availability: Dict[str, bool] = Field(default_factory=dict)
    model_availability: Dict[str, bool] = Field(default_factory=dict)

    @property
    def errors(self) -> List[ConfigurationIssue]:
        """Return error-severity issues."""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[ConfigurationIssue]:
        """Return warning-severity issues."""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def is_healthy(self) -> bool:
        """Return True when no error-severity issues exist."""
        return not self.errors

    def add_issue(self, name: str, message: str, severity: str = "error") -> None:
        """Append an issue to the collection."""
        self.issues.append(ConfigurationIssue(name=name, message=message, severity=severity))


class AppSettings(BaseSettings):
    """
    Infrastructure settings loaded from environment variables.

    Only infrastructure-level values remain in the environment. Secrets are
    handled separately via the secrets store.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=True)

    vaults_root_path: Optional[Path] = Field(default=None, alias="VAULTS_ROOT_PATH")

    _LLM_SECRET_KEYS = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROK_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
    ]

    @field_validator("vaults_root_path", mode="before")
    @classmethod
    def _expand_vault_path(cls, value):
        """Expand user paths to absolute Path instances."""
        if value in (None, ""):
            return None
        if isinstance(value, Path):
            return value.expanduser()
        return Path(value).expanduser()

    def available_llm_keys(self) -> Dict[str, str]:
        """
        Return a mapping of LLM API key secret names to values.
        """
        secrets = load_secrets(include_empty=False)
        return {
            key: value
            for key, value in secrets.items()
            if key in self._LLM_SECRET_KEYS
        }

    def has_any_llm_key(self) -> bool:
        """Return True when at least one LLM API key is configured."""
        return any(secret_has_value(name) for name in self._LLM_SECRET_KEYS)

    def required_env_keys(self) -> Dict[str, Optional[str]]:
        """
        Return a mapping of required environment variable names to their values.

        Used by validation routines to produce targeted warnings.
        """
        required = {"VAULTS_ROOT_PATH": self.vaults_root_path}
        return required


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """
    Load application settings from environment variables.
    """
    return AppSettings()


def refresh_app_settings_cache() -> None:
    """Clear cached settings so future calls reload from environment."""
    get_app_settings.cache_clear()  # type: ignore[attr-defined]


def validate_settings(
    settings: Optional[AppSettings] = None,
    tools_config: Optional[Dict[str, ToolConfig]] = None,
    models_config: Optional[Dict[str, ModelConfig]] = None,
    providers_config: Optional[Dict[str, ProviderConfig]] = None,
) -> ConfigurationStatus:
    """
    Validate core configuration requirements.

    Args:
        settings: Optional pre-loaded AppSettings instance.

    Returns:
        ConfigurationStatus describing any issues discovered.
    """
    active_settings = settings or get_app_settings()
    status = ConfigurationStatus()
    template_sections = _load_template_sections()

    if not active_settings.has_any_llm_key():
        status.add_issue(
            name="LLM_API_KEYS",
            message="Add at least one LLM API key under Secrets in the Configuration tab.",
            severity="warning",
        )

    tools = tools_config or get_tools_config()
    for tool_name, tool_config in tools.items():
        required_secrets = []
        if hasattr(tool_config, "required_secret_keys"):
            required_secrets = tool_config.required_secret_keys()
        missing_secrets = [key for key in required_secrets if not secret_has_value(key)]
        status.tool_availability[tool_name] = not missing_secrets
        if missing_secrets:
            status.add_issue(
                name=f"tool:{tool_name}",
                message=f"Tool '{tool_name}' unavailable until secrets {missing_secrets} are configured.",
                severity="warning",
            )

    providers = providers_config or get_providers_config()
    models = models_config or get_models_config()
    for model_name, model_config in models.items():
        provider_name = getattr(model_config, "provider", None) or (
            model_config.get("provider") if isinstance(model_config, dict) else None
        )
        status.model_availability[model_name] = True
        if not provider_name:
            continue

        provider_config = providers.get(provider_name)
        if provider_config is None:
            status.model_availability[model_name] = False
            status.add_issue(
                name=f"model:{model_name}",
                message=f"Model '{model_name}' references unknown provider '{provider_name}'.",
            )
            continue

        api_key_name = getattr(provider_config, "api_key", None)
        if isinstance(api_key_name, str) and api_key_name.lower() != "null" and api_key_name:
            if not secret_has_value(api_key_name):
                status.model_availability[model_name] = False
                status.add_issue(
                    name=f"model:{model_name}",
                    message=f"Configure {api_key_name}",
                    severity="warning",
                )

    _add_missing_template_issues(
        status,
        template_sections=template_sections,
        active_sections={
            "settings": set((get_general_settings() or {}).keys()),
            "models": set(models.keys()),
            "providers": set(providers.keys()),
            "tools": set(tools.keys()),
        },
    )

    def _is_user_editable(entry: Any, default: bool) -> bool:
        """Best-effort user_editable check for typed/dict entries."""
        if hasattr(entry, "user_editable"):
            try:
                return bool(entry.user_editable)
            except Exception:
                return default
        if isinstance(entry, dict):
            val = entry.get("user_editable")
            if isinstance(val, bool):
                return val
        return default

    # Settings are not user-extensible; flag extras
    settings_template_keys = template_sections.get("settings", set())
    settings_extra = set((get_general_settings() or {}).keys()) - settings_template_keys
    if settings_extra:
        status.add_issue(
            name="settings:extra",
            message=f"Unknown settings present: {', '.join(sorted(settings_extra))}",
            severity="warning",
        )

    def _warn_extras(section_name: str, items: Dict[str, Any], default_user_editable: bool):
        template_keys = template_sections.get(section_name, set())
        for key, entry in items.items():
            if key in template_keys:
                continue
            if _is_user_editable(entry, default_user_editable):
                continue
            status.add_issue(
                name=f"{section_name}:extra",
                message=f"Unknown {section_name.rstrip('s')} '{key}' present; run settings repair to clean up.",
                severity="warning",
            )

    _warn_extras("tools", tools, default_user_editable=False)
    _warn_extras("models", models, default_user_editable=True)
    _warn_extras("providers", providers, default_user_editable=False)

    return status


@lru_cache(maxsize=1)
def get_configuration_status() -> ConfigurationStatus:
    """Return cached configuration status assessment."""
    return validate_settings()


def refresh_configuration_status_cache() -> None:
    """Clear cached configuration status."""
    get_configuration_status.cache_clear()  # type: ignore[attr-defined]


def _load_template_sections() -> Dict[str, set]:
    """Load template keys for each section to detect missing entries."""
    try:
        raw = yaml.safe_load(SETTINGS_TEMPLATE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    sections: Dict[str, set] = {}
    for section in ("settings", "models", "providers", "tools"):
        section_data = raw.get(section)
        if isinstance(section_data, dict):
            sections[section] = set(section_data.keys())
    return sections


def _add_missing_template_issues(
    status: ConfigurationStatus,
    template_sections: Dict[str, set],
    active_sections: Dict[str, set],
) -> None:
    """
    Add warning issues for keys missing in active settings compared to the template.
    """
    for section, template_keys in template_sections.items():
        if not template_keys:
            continue
        missing = template_keys - active_sections.get(section, set())
        if missing:
            status.add_issue(
                name=f"{section}:missing",
                message=f"Settings missing from template: {', '.join(sorted(missing))}",
                severity="warning",
            )


def get_default_api_timeout() -> float:
    """Return the configured API timeout, falling back to 120 seconds."""
    entry = get_general_settings().get("default_api_timeout")
    value = getattr(entry, "value", None) if entry is not None else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return 120.0


def get_default_max_output_tokens() -> int:
    """Return the configured max output tokens, falling back to 0 (provider default)."""
    entry = get_general_settings().get("max_output_tokens")
    value = getattr(entry, "value", None) if entry is not None else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def get_auto_buffer_max_tokens() -> int:
    """Return the configured auto-buffer token limit, falling back to 0 (disabled)."""
    entry = get_general_settings().get("auto_buffer_max_tokens")
    value = getattr(entry, "value", None) if entry is not None else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
