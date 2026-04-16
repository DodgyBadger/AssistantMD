"""Pydantic AI model instance construction.

Builds configured Pydantic AI model objects from user-friendly alias strings.
Extracted from ModelDirective so non-DSL callers (chat executor, agent builder)
can construct models without depending on the directive execution machinery.
"""

from __future__ import annotations

from pydantic_ai.models.test import TestModel
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import (
    OpenAIModel,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.models.mistral import MistralModel
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.mistral import MistralProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.grok import GrokProvider
from pydantic_ai.settings import ModelSettings

from core.llm.model_utils import resolve_model, validate_api_keys, get_provider_config
from core.llm.model_selection import ModelExecutionSpec, resolve_model_execution_spec
from core.settings import get_default_api_timeout, get_default_max_output_tokens
from core.settings.secrets_store import get_secret_value
from core.utils.value_parser import DirectiveValueParser


def _resolve_config_value(raw_value: str | None) -> str | None:
    """Resolve a provider config value as secret name first, then literal value."""
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value or value.lower() == "null":
        return None
    return get_secret_value(value) or value


def build_model_instance(value: str) -> ModelExecutionSpec | object:
    """Build a Pydantic AI model instance from a user-friendly alias string.

    Args:
        value: Model alias with optional parameters, e.g. ``"sonnet"``,
               ``"sonnet (thinking)"``, or ``"none"`` for skip mode.

    Returns:
        A configured Pydantic AI model instance ready for agent creation, or a
        :class:`~core.llm.model_selection.ModelExecutionSpec` in skip mode for
        aliases like ``"none"``.

    Raises:
        ValueError: If the alias is empty, unrecognised, or API keys are missing.
    """
    if DirectiveValueParser.is_empty(value):
        raise ValueError("Model name cannot be empty")

    model_name, parameters = DirectiveValueParser.parse_value_with_parameters(
        value, allowed_parameters={"thinking"}
    )
    normalized_model = DirectiveValueParser.normalize_string(model_name, to_lower=True)

    execution = resolve_model_execution_spec(value)
    if execution.mode == "skip":
        return execution

    if normalized_model == "test":
        return TestModel()

    validate_api_keys(normalized_model)
    provider, model_string = resolve_model(normalized_model)

    enable_thinking = parameters.get("thinking", "false").lower() == "true"

    if provider == "google":
        settings_kwargs = {"timeout": get_default_api_timeout()}
        max_output_tokens = get_default_max_output_tokens()
        if max_output_tokens > 0:
            settings_kwargs["max_tokens"] = max_output_tokens
        api_key = get_secret_value("GOOGLE_API_KEY")
        return GoogleModel(
            model_string,
            provider=GoogleProvider(api_key=api_key),
            settings=GoogleModelSettings(**settings_kwargs),
        )

    elif provider == "anthropic":
        settings_kwargs = {"timeout": get_default_api_timeout()}
        max_output_tokens = get_default_max_output_tokens()
        if max_output_tokens > 0:
            settings_kwargs["max_tokens"] = max_output_tokens
        if enable_thinking:
            settings_kwargs["anthropic_thinking"] = {
                "type": "enabled",
                "budget_tokens": 2000,
            }
        api_key = get_secret_value("ANTHROPIC_API_KEY")
        return AnthropicModel(
            model_string,
            provider=AnthropicProvider(api_key=api_key),
            settings=AnthropicModelSettings(**settings_kwargs),
        )

    elif provider == "openai":
        settings_kwargs = {"timeout": get_default_api_timeout()}
        max_output_tokens = get_default_max_output_tokens()
        if max_output_tokens > 0:
            settings_kwargs["max_tokens"] = max_output_tokens
        provider_config = get_provider_config(provider)
        api_key = _resolve_config_value(provider_config.get("api_key"))
        base_url = _resolve_config_value(provider_config.get("base_url"))
        return OpenAIResponsesModel(
            model_string,
            provider=OpenAIProvider(api_key=api_key, base_url=base_url),
            settings=OpenAIResponsesModelSettings(**settings_kwargs),
        )

    elif provider == "grok":
        settings_kwargs = {"timeout": get_default_api_timeout()}
        max_output_tokens = get_default_max_output_tokens()
        if max_output_tokens > 0:
            settings_kwargs["max_tokens"] = max_output_tokens
        api_key = get_secret_value("GROK_API_KEY")
        return OpenAIModel(
            model_string,
            provider=GrokProvider(api_key=api_key),
            settings=OpenAIResponsesModelSettings(**settings_kwargs),
        )

    elif provider == "mistral":
        settings_kwargs = {"timeout": get_default_api_timeout()}
        max_output_tokens = get_default_max_output_tokens()
        if max_output_tokens > 0:
            settings_kwargs["max_tokens"] = max_output_tokens
        api_key = get_secret_value("MISTRAL_API_KEY")
        return MistralModel(
            model_string,
            provider=MistralProvider(api_key=api_key),
            settings=ModelSettings(**settings_kwargs),
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
        settings_kwargs = {"timeout": get_default_api_timeout()}
        max_output_tokens = get_default_max_output_tokens()
        if max_output_tokens > 0:
            settings_kwargs["max_tokens"] = max_output_tokens

        api_key = _resolve_config_value(provider_config.get("api_key"))
        return OpenAIModel(
            model_string,
            provider=OpenAIProvider(api_key=api_key, base_url=base_url),
            settings=ModelSettings(**settings_kwargs),
        )
