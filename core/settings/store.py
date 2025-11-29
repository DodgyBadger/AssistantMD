"""
Settings file loader and helpers.

Provides typed access to `system/settings.yaml`, covering general settings,
models, providers, and tool metadata. Replaces the legacy mappings loader.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field, ValidationError

from core.runtime.paths import get_system_root


SETTINGS_TEMPLATE = Path(__file__).parent / "settings.template.yaml"


class SettingsEntry(BaseModel):
    """Single general settings entry."""

    value: Any
    description: str | None = None
    restart_required: bool = False


class ToolConfig(BaseModel):
    """Configuration for a single tool entry."""

    module: str
    description: str | None = None
    requires_secrets: list[str] = Field(default_factory=list)
    user_editable: bool = False

    def required_secret_keys(self) -> list[str]:
        return list(self.requires_secrets)


class ProviderConfig(BaseModel):
    """Configuration for a model provider."""

    api_key: str | None = None
    base_url: str | None = None
    user_editable: bool = False


class ModelConfig(BaseModel):
    """Configuration for a model mapping."""

    provider: str
    model_string: str
    description: str | None = None
    user_editable: bool = True


class SettingsFile(BaseModel):
    """Root schema for settings.yaml content."""

    settings: Dict[str, SettingsEntry] = Field(default_factory=dict)
    models: Dict[str, ModelConfig] = Field(default_factory=dict)
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
    tools: Dict[str, ToolConfig] = Field(default_factory=dict)


def _resolve_system_root() -> Path:
    """
    Determine the active system root, preferring runtime context over defaults.

    Falls back to environment/default constants when a runtime context has not
    been established (e.g. before bootstrap).
    """
    return get_system_root()


def _resolve_settings_path() -> Path:
    """Determine the active settings file path."""
    return _resolve_system_root() / "settings.yaml"


def _ensure_settings_file(target_path: Path) -> None:
    """Ensure the settings file exists at the target path, seeding from template if missing."""
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        return

    if not SETTINGS_TEMPLATE.exists():
        raise FileNotFoundError(f"Default settings template missing: {SETTINGS_TEMPLATE}")

    shutil.copyfile(SETTINGS_TEMPLATE, target_path)


@lru_cache(maxsize=1)
def load_settings() -> SettingsFile:
    """
    Load complete settings.yaml configuration with caching.

    Returns:
        SettingsFile model for general settings, models, providers, and tools.
    """
    settings_file = get_active_settings_path()

    with open(settings_file, "r", encoding="utf-8") as handle:
        raw_data = yaml.safe_load(handle) or {}

    for section in ("settings", "models", "providers", "tools"):
        if raw_data.get(section) is None:
            raw_data[section] = {}

    try:
        return SettingsFile.model_validate(raw_data)
    except ValidationError as exc:
        raise ValueError(f"Invalid settings.yaml configuration: {exc}") from exc


def refresh_settings_cache() -> None:
    """Clear the settings cache so future calls reload from disk."""
    load_settings.cache_clear()  # type: ignore[attr-defined]


def save_settings(settings: SettingsFile) -> None:
    """Persist settings configuration to disk using atomic write."""
    path = get_active_settings_path()
    data = settings.model_dump(mode="python")

    tmp_path = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(tmp_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=False)

    os.replace(tmp_path, path)


def get_active_settings_path() -> Path:
    """Return the active settings file path, ensuring it exists."""
    path = _resolve_settings_path()
    _ensure_settings_file(path)
    return path


def get_general_settings() -> Dict[str, SettingsEntry]:
    """Get general settings section."""
    return load_settings().settings


def get_tools_config() -> Dict[str, ToolConfig]:
    """Get tools configuration section from settings."""
    return load_settings().tools


def get_models_config() -> Dict[str, ModelConfig]:
    """Get models configuration section from settings."""
    return load_settings().models


def get_providers_config() -> Dict[str, ProviderConfig]:
    """Get providers configuration section from settings."""
    return load_settings().providers
