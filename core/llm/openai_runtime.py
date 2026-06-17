"""OpenAI provider construction for API-key and OAuth auth modes."""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from openai import AsyncOpenAI
from pydantic_ai.providers.openai import OpenAIProvider

from core.llm.openai_auth import (
    OPENAI_AUTH_MODE_API_KEY,
    OPENAI_AUTH_MODE_OAUTH,
    OpenAIAuthResolution,
    resolve_openai_auth,
)
from core.llm.openai_oauth import (
    get_openai_oauth_status,
    ensure_fresh_openai_oauth_token,
    load_openai_oauth_token_state,
)
from core.settings.secrets_store import get_secret_value, secret_has_value
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


OPENAI_CHATGPT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


class DefaultOpenAIOAuthRuntimeAdapter:
    """Build a Pydantic AI OpenAI provider backed by ChatGPT OAuth tokens."""

    def build_provider(
        self,
        *,
        provider_config: dict[str, Any],
        resolution: OpenAIAuthResolution,
        http_client: httpx.AsyncClient,
    ) -> OpenAIProvider:
        """Return an OpenAI provider using the ChatGPT Codex backend."""

        token_state = load_openai_oauth_token_state()
        if token_state is None:
            raise ValueError("OpenAI OAuth is selected but no token is stored.")

        async def bearer_token() -> str:
            refreshed = await ensure_fresh_openai_oauth_token()
            return refreshed.access_token

        headers = {}
        if token_state.account_id:
            headers["ChatGPT-Account-ID"] = token_state.account_id

        client = AsyncOpenAI(
            api_key=bearer_token,
            base_url=OPENAI_CHATGPT_CODEX_BASE_URL,
            default_headers=headers or None,
            http_client=http_client,
        )
        return OpenAIProvider(openai_client=client)


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
        oauth_connected=get_openai_oauth_status().connected,
        api_key_available=_has_configured_api_key(provider_config),
        base_url_available=bool(base_url),
    )

    if resolution.effective_auth_mode == OPENAI_AUTH_MODE_API_KEY:
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )

    if resolution.effective_auth_mode == OPENAI_AUTH_MODE_OAUTH:
        adapter = _oauth_runtime_adapter or DefaultOpenAIOAuthRuntimeAdapter()
        return adapter.build_provider(
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


def _has_configured_api_key(provider_config: dict[str, Any]) -> bool:
    api_key_name = provider_config.get("api_key")
    return bool(
        isinstance(api_key_name, str)
        and api_key_name
        and api_key_name.lower() != "null"
        and secret_has_value(api_key_name)
    )


def _resolve_config_value(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value or value.lower() == "null":
        return None
    return get_secret_value(value) or value
