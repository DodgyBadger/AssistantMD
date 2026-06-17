"""OpenAI provider construction for API-key and OAuth auth modes."""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic_ai.providers.openai import OpenAIProvider

from core.llm.openai_oauth import (
    OPENAI_AUTH_MODE_API_KEY,
    OPENAI_AUTH_MODE_OAUTH,
    OpenAIAuthResolution,
    resolve_openai_auth,
)
from core.settings.secrets_store import get_secret_value
from core.settings.store import get_general_settings


class OpenAIOAuthRuntimeAdapter(Protocol):
    """Adapter boundary for OAuth-backed OpenAI provider construction."""

    def build_provider(
        self,
        *,
        provider_config: dict[str, Any],
        resolution: OpenAIAuthResolution,
        http_client: httpx.AsyncClient,
    ) -> OpenAIProvider:
        """Return a Pydantic AI OpenAI provider for OAuth-backed runtime use."""


_oauth_runtime_adapter: OpenAIOAuthRuntimeAdapter | None = None


def set_openai_oauth_runtime_adapter(
    adapter: OpenAIOAuthRuntimeAdapter | None,
) -> None:
    """Set the process-local OAuth runtime adapter."""

    global _oauth_runtime_adapter
    _oauth_runtime_adapter = adapter


def build_openai_provider(
    *,
    provider_config: dict[str, Any],
    http_client: httpx.AsyncClient,
) -> OpenAIProvider:
    """Build an OpenAI provider according to the effective auth mode."""

    api_key = _resolve_config_value(provider_config.get("api_key"))
    base_url = _resolve_config_value(provider_config.get("base_url"))
    resolution = resolve_openai_auth(
        provider_config,
        oauth_enabled=_openai_oauth_enabled(),
        base_url_available=bool(base_url),
    )

    if resolution.effective_auth_mode == OPENAI_AUTH_MODE_API_KEY:
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )

    if resolution.effective_auth_mode == OPENAI_AUTH_MODE_OAUTH:
        if _oauth_runtime_adapter is None:
            raise ValueError(
                "OpenAI OAuth runtime adapter is not configured. "
                "Switch OpenAI back to API-key auth or disable OpenAI OAuth."
            )
        return _oauth_runtime_adapter.build_provider(
            provider_config=provider_config,
            resolution=resolution,
            http_client=http_client,
        )

    raise ValueError(
        f"Unsupported OpenAI auth mode '{resolution.effective_auth_mode}'."
    )


def _openai_oauth_enabled() -> bool:
    entry = get_general_settings().get("openai_oauth_enabled")
    return bool(getattr(entry, "value", False))


def _resolve_config_value(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value or value.lower() == "null":
        return None
    return get_secret_value(value) or value
