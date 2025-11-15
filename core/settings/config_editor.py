"""
Configuration editing helpers for settings.yaml.

Provides validated update operations for user-facing configuration surfaces
such as model mappings and custom providers while preserving developer-only
sections (tools, core providers).
"""

import json
from typing import Optional

from core.settings.store import (
    ModelConfig,
    ProviderConfig,
    SettingsEntry,
    load_settings,
    save_settings,
    refresh_settings_cache,
)
from . import SettingsError, refresh_configuration_status_cache


def _persist_changes(settings_file) -> None:
    """Persist settings to disk and refresh related caches."""
    save_settings(settings_file)
    refresh_settings_cache()
    refresh_configuration_status_cache()


def list_general_settings() -> dict[str, SettingsEntry]:
    """Return general settings entries."""
    return load_settings().settings


def update_general_setting(name: str, raw_value: str) -> SettingsEntry:
    """Update a general setting value while preserving metadata and types."""
    settings_file = load_settings()
    entry = settings_file.settings.get(name)

    if entry is None:
        raise SettingsError(f"Setting '{name}' does not exist.")

    coerced_value = _coerce_setting_value(raw_value, entry.value)
    settings_file.settings[name] = SettingsEntry(
        value=coerced_value,
        description=entry.description,
        restart_required=entry.restart_required,
    )

    _persist_changes(settings_file)
    return settings_file.settings[name]


def _coerce_setting_value(raw_value: str, current_value):
    """Attempt to convert the provided raw string into the original setting type."""
    raw_value = raw_value if raw_value is not None else ""

    if isinstance(current_value, bool):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise SettingsError("Value must be true or false.")

    if isinstance(current_value, int) and not isinstance(current_value, bool):
        try:
            return int(raw_value.strip())
        except ValueError as exc:
            raise SettingsError("Value must be an integer.") from exc

    if isinstance(current_value, float):
        try:
            return float(raw_value.strip())
        except ValueError as exc:
            raise SettingsError("Value must be a number.") from exc

    if current_value is None:
        return raw_value or None

    if isinstance(current_value, (list, dict)):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise SettingsError("Value must be valid JSON for this setting.") from exc
        if not isinstance(parsed, type(current_value)):
            raise SettingsError("Updated value type does not match existing setting type.")
        return parsed

    return raw_value


def upsert_model_mapping(
    name: str,
    provider: str,
    model_string: str,
    description: Optional[str] = None,
) -> ModelConfig:
    """
    Create or update a model mapping entry.

    Args:
        name: Model alias (lowercase string used by workflows)
        provider: Provider name the model depends on
        model_string: Provider-specific model identifier
        description: Optional human-readable description

    Returns:
        Updated ModelConfig instance

    Raises:
        SettingsError: When attempting to modify a non-editable entry or
                       reference an unknown provider.
    """
    settings_file = load_settings()
    existing = settings_file.models.get(name)

    if existing and not getattr(existing, "user_editable", True):
        raise SettingsError(f"Model '{name}' is not user editable.")

    if provider not in settings_file.providers:
        raise SettingsError(f"Provider '{provider}' is not defined in settings.yaml.")

    user_editable = getattr(existing, "user_editable", True) if existing else True

    settings_file.models[name] = ModelConfig(
        provider=provider,
        model_string=model_string,
        description=description,
        user_editable=user_editable,
    )

    _persist_changes(settings_file)
    return settings_file.models[name]


def delete_model_mapping(name: str) -> None:
    """Delete a user-editable model mapping."""
    settings_file = load_settings()
    existing = settings_file.models.get(name)

    if not existing:
        raise SettingsError(f"Model '{name}' does not exist.")

    if not getattr(existing, "user_editable", True):
        raise SettingsError(f"Model '{name}' is not user editable.")

    del settings_file.models[name]
    _persist_changes(settings_file)


def upsert_provider_config(
    name: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ProviderConfig:
    """
    Create or update a provider configuration entry.

    Only providers marked as user_editable (or new providers) may be modified.
    """
    settings_file = load_settings()
    existing = settings_file.providers.get(name)

    if existing and not getattr(existing, "user_editable", False):
        raise SettingsError(f"Provider '{name}' is not user editable.")

    user_editable = getattr(existing, "user_editable", True) if existing else True

    settings_file.providers[name] = ProviderConfig(
        api_key=api_key,
        base_url=base_url,
        user_editable=user_editable,
    )

    _persist_changes(settings_file)
    return settings_file.providers[name]


def delete_provider_config(name: str) -> None:
    """Delete a user-editable provider configuration if unused."""
    settings_file = load_settings()
    existing = settings_file.providers.get(name)

    if not existing:
        raise SettingsError(f"Provider '{name}' does not exist.")

    if not getattr(existing, "user_editable", False):
        raise SettingsError(f"Provider '{name}' is not user editable.")

    dependent_models = [
        model_name
        for model_name, model_config in settings_file.models.items()
        if getattr(model_config, "provider", None) == name
    ]

    if dependent_models:
        joined = ", ".join(sorted(dependent_models))
        raise SettingsError(
            f"Provider '{name}' cannot be removed while models reference it ({joined})."
        )

    del settings_file.providers[name]
    _persist_changes(settings_file)
