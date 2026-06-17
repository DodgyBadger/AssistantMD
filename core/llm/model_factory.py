"""Pydantic AI model instance construction."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import (
    OpenAIModel,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.models.mistral import MistralModel
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.providers.mistral import MistralProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.grok import GrokProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from pydantic_ai.settings import ModelSettings
from tenacity import retry_if_exception, stop_after_attempt

from core.llm.thinking import ThinkingValue
from core.llm.model_utils import resolve_model, validate_api_keys, get_provider_config
from core.llm.model_selection import ModelExecutionSpec, resolve_model_execution_spec
from core.llm.openai_runtime import build_openai_provider
from core.settings import (
    get_default_api_timeout,
    get_default_max_output_tokens,
    get_openrouter_ignored_providers,
)
from core.settings.secrets_store import get_secret_value
from core.utils.value_parser import DirectiveValueParser
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="model-factory")
_MODEL_HTTP_RETRY_ATTEMPTS = 3
_MODEL_HTTP_RETRY_MAX_WAIT_SECONDS = 30.0


def _resolve_config_value(raw_value: str | None) -> str | None:
    """Resolve a provider config value as secret name first, then literal value."""
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value or value.lower() == "null":
        return None
    return get_secret_value(value) or value


def _base_settings_kwargs(thinking: ThinkingValue) -> dict[str, object]:
    """Build common model settings shared across providers."""
    settings_kwargs: dict[str, object] = {"timeout": get_default_api_timeout()}
    max_output_tokens = get_default_max_output_tokens()
    if max_output_tokens > 0:
        settings_kwargs["max_tokens"] = max_output_tokens
    if thinking is not None:
        settings_kwargs["thinking"] = thinking
    return settings_kwargs


def _apply_openrouter_settings(
    settings_kwargs: dict[str, object],
    provider_config: dict[str, Any],
) -> None:
    """Map AssistantMD OpenRouter provider config onto Pydantic AI settings."""
    openrouter_provider = provider_config.get("provider")
    provider_settings = dict(openrouter_provider) if isinstance(openrouter_provider, dict) else {}
    ignored_providers = get_openrouter_ignored_providers()
    if ignored_providers:
        configured_ignore = provider_settings.get("ignore")
        if isinstance(configured_ignore, list):
            merged_ignore = [
                str(item).strip().lower()
                for item in configured_ignore
                if str(item).strip()
            ]
        else:
            merged_ignore = []
        seen = set(merged_ignore)
        for provider in ignored_providers:
            if provider not in seen:
                merged_ignore.append(provider)
                seen.add(provider)
        provider_settings["ignore"] = merged_ignore
    if provider_settings:
        settings_kwargs["openrouter_provider"] = provider_settings


def _is_retryable_model_http_exception(exc: BaseException) -> bool:
    """Return whether Pydantic AI model HTTP transport should retry the exception."""
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or 500 <= status_code <= 599
    return isinstance(exc, httpx.RequestError)


def _raise_retryable_model_status(response: httpx.Response) -> None:
    """Raise only retryable HTTP statuses inside the transport retry layer."""
    if response.status_code == 429 or 500 <= response.status_code <= 599:
        response.raise_for_status()


def _log_model_retry_before_sleep(retry_state) -> None:
    """Emit one lifecycle event before Pydantic AI retry transport sleeps."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.add_sink("validation").warning(
        "model_http_retry_scheduled",
        data={
            "event": "model_http_retry_scheduled",
            "attempt": retry_state.attempt_number,
            "next_action": "retry",
            "delay_seconds": (
                None
                if retry_state.next_action is None
                else retry_state.next_action.sleep
            ),
            "error_type": None if exc is None else type(exc).__name__,
            "http_status": (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            ),
        },
    )


def _build_retrying_model_http_client() -> httpx.AsyncClient:
    """Build the Pydantic AI provider HTTP client with bounded retry transport."""
    retry_config = RetryConfig(
        retry=retry_if_exception(_is_retryable_model_http_exception),
        wait=wait_retry_after(max_wait=_MODEL_HTTP_RETRY_MAX_WAIT_SECONDS),
        stop=stop_after_attempt(_MODEL_HTTP_RETRY_ATTEMPTS),
        before_sleep=_log_model_retry_before_sleep,
        reraise=True,
    )
    transport = AsyncTenacityTransport(
        retry_config,
        validate_response=_raise_retryable_model_status,
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=float(get_default_api_timeout()),
    )


def _mark_provider_owns_http_client(provider: object, http_client: httpx.AsyncClient) -> object:
    """Mark a custom retry client as provider-owned for Pydantic AI lifecycle hooks."""
    setattr(provider, "_own_http_client", http_client)
    setattr(provider, "_http_client_factory", _build_retrying_model_http_client)
    return provider


def build_model_instance(value: str, *, thinking: ThinkingValue = None) -> ModelExecutionSpec | object:
    """Build a Pydantic AI model instance from a user-friendly alias string.

    Args:
        value: Model alias, e.g. ``"sonnet"`` or ``"none"`` for skip mode.

    Returns:
        A configured Pydantic AI model instance ready for agent creation, or a
        :class:`~core.llm.model_selection.ModelExecutionSpec` in skip mode for
        aliases like ``"none"``.

    Raises:
        ValueError: If the alias is empty, unrecognised, or API keys are missing.
    """
    if DirectiveValueParser.is_empty(value):
        raise ValueError("Model name cannot be empty")

    model_name, parameters = DirectiveValueParser.parse_value_with_parameters(value)
    if parameters:
        raise ValueError(
            "Model alias parameters are no longer supported. Pass thinking as a separate option or setting."
        )
    normalized_model = DirectiveValueParser.normalize_string(model_name, to_lower=True)

    execution = resolve_model_execution_spec(value)
    if execution.mode == "skip":
        return execution

    if normalized_model == "test":
        return TestModel()

    validate_api_keys(normalized_model)
    provider, model_string = resolve_model(normalized_model)

    if provider == "google":
        settings_kwargs = _base_settings_kwargs(thinking)
        api_key = get_secret_value("GOOGLE_API_KEY")
        http_client = _build_retrying_model_http_client()
        return GoogleModel(
            model_string,
            provider=_mark_provider_owns_http_client(
                GoogleProvider(api_key=api_key, http_client=http_client),
                http_client,
            ),
            settings=GoogleModelSettings(**settings_kwargs),
        )

    elif provider == "anthropic":
        settings_kwargs = _base_settings_kwargs(thinking)
        api_key = get_secret_value("ANTHROPIC_API_KEY")
        http_client = _build_retrying_model_http_client()
        return AnthropicModel(
            model_string,
            provider=_mark_provider_owns_http_client(
                AnthropicProvider(api_key=api_key, http_client=http_client),
                http_client,
            ),
            settings=AnthropicModelSettings(**settings_kwargs),
        )

    elif provider == "openai":
        settings_kwargs = _base_settings_kwargs(thinking)
        provider_config = get_provider_config(provider)
        http_client = _build_retrying_model_http_client()
        openai_provider = build_openai_provider(
            provider_config=provider_config,
            http_client=http_client,
        )
        return OpenAIResponsesModel(
            model_string,
            provider=_mark_provider_owns_http_client(
                openai_provider,
                http_client,
            ),
            settings=OpenAIResponsesModelSettings(**settings_kwargs),
        )

    elif provider == "grok":
        settings_kwargs = _base_settings_kwargs(thinking)
        api_key = get_secret_value("GROK_API_KEY")
        http_client = _build_retrying_model_http_client()
        return OpenAIModel(
            model_string,
            provider=_mark_provider_owns_http_client(
                GrokProvider(api_key=api_key, http_client=http_client),
                http_client,
            ),
            settings=OpenAIResponsesModelSettings(**settings_kwargs),
        )

    elif provider == "mistral":
        settings_kwargs = _base_settings_kwargs(thinking)
        api_key = get_secret_value("MISTRAL_API_KEY")
        http_client = _build_retrying_model_http_client()
        return MistralModel(
            model_string,
            provider=_mark_provider_owns_http_client(
                MistralProvider(api_key=api_key, http_client=http_client),
                http_client,
            ),
            settings=ModelSettings(**settings_kwargs),
        )

    elif provider == "openrouter":
        settings_kwargs = _base_settings_kwargs(thinking)
        provider_config = get_provider_config(provider)
        api_key = _resolve_config_value(provider_config.get("api_key"))
        _apply_openrouter_settings(settings_kwargs, provider_config)
        http_client = _build_retrying_model_http_client()
        return OpenRouterModel(
            model_string,
            provider=_mark_provider_owns_http_client(
                OpenRouterProvider(api_key=api_key, http_client=http_client),
                http_client,
            ),
            settings=OpenRouterModelSettings(**settings_kwargs),
        )

    else:
        # Any other provider is treated as an OpenAI-compatible endpoint
        # (Ollama, LM Studio, vLLM, etc.)
        provider_config = get_provider_config(provider)
        base_url_config = provider_config.get("base_url")

        if not base_url_config:
            raise ValueError(
                f"Provider '{provider}' requires 'base_url' to be configured in "
                f"system/settings.yaml. Set providers.{provider}.base_url to a literal "
                f"URL or the name of a stored secret."
            )

        base_url = _resolve_config_value(base_url_config)
        settings_kwargs = _base_settings_kwargs(thinking)

        api_key = _resolve_config_value(provider_config.get("api_key"))
        http_client = _build_retrying_model_http_client()
        return OpenAIModel(
            model_string,
            provider=_mark_provider_owns_http_client(
                OpenAIProvider(api_key=api_key, base_url=base_url, http_client=http_client),
                http_client,
            ),
            settings=ModelSettings(**settings_kwargs),
        )
