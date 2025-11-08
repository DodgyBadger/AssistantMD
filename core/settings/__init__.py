"""
Application settings and configuration health utilities.

Provides a single typed interface for environment-driven settings along with
helpers to diagnose missing configuration required for runtime features.
"""

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.settings.store import (
    ModelConfig,
    ProviderConfig,
    ToolConfig,
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
        "GEMINI_API_KEY",
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

    if not active_settings.has_any_llm_key():
        status.add_issue(
            name="LLM_API_KEYS",
            message=(
                "No LLM API keys configured yet. Configure at least one secret "
                "for OPENAI, ANTHROPIC, GEMINI, MISTRAL, or DEEPSEEK to enable "
                "production model usage."
            ),
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

    return status


@lru_cache(maxsize=1)
def get_configuration_status() -> ConfigurationStatus:
    """Return cached configuration status assessment."""
    return validate_settings()


def refresh_configuration_status_cache() -> None:
    """Clear cached configuration status."""
    get_configuration_status.cache_clear()  # type: ignore[attr-defined]


def get_default_api_timeout() -> float:
    """Return the configured API timeout, falling back to 120 seconds."""
    entry = get_general_settings().get("default_api_timeout")
    value = getattr(entry, "value", None) if entry is not None else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return 120.0


def get_web_tool_max_tokens() -> int:
    """Return the configured web tool token limit, falling back to 50000 tokens."""
    entry = get_general_settings().get("web_tool_max_tokens")
    value = getattr(entry, "value", None) if entry is not None else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return 50000
