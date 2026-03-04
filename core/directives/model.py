"""
Model directive processor.

Handles @model directive for per-step model selection using user-friendly model names.
"""

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

from .base import DirectiveProcessor
from .parser import DirectiveValueParser
from core.llm.model_utils import resolve_model, validate_api_keys, get_provider_config
from core.llm.model_selection import resolve_model_execution_spec
from core.settings import get_default_api_timeout, get_default_max_output_tokens
from core.settings.secrets_store import get_secret_value


class ModelDirective(DirectiveProcessor):
    """Processor for @model directive that specifies which AI model to use for a step."""

    @staticmethod
    def _resolve_config_value(raw_value: str | None) -> str | None:
        """Resolve a provider config value as secret name first, then literal value."""
        if raw_value is None:
            return None

        value = raw_value.strip()
        if not value or value.lower() == "null":
            return None

        return get_secret_value(value) or value
    
    def get_directive_name(self) -> str:
        return "model"
    
    def validate_value(self, value: str) -> bool:
        """Validate that the model name is recognized and parameters are valid."""
        if DirectiveValueParser.is_empty(value):
            return False
        
        try:
            execution = resolve_model_execution_spec(value)
            if execution.mode == "skip":
                return True

            # Parse model name and parameters
            model_name, parameters = DirectiveValueParser.parse_value_with_parameters(
                value, allowed_parameters={"thinking"}
            )
            normalized_model = DirectiveValueParser.normalize_string(model_name, to_lower=True)

            if normalized_model == 'test':
                return True

            # Validate model exists
            resolve_model(normalized_model)
            
            # Validate parameters (currently only 'thinking' is supported)
            for param_name, param_value in parameters.items():
                if param_name.lower() != 'thinking':
                    return False
                # Validate thinking parameter is a boolean-like value
                if param_value.lower() not in ['true', 'false']:
                    return False
            
            return True
        except ValueError:
            return False
    
    def process_value(self, value: str, vault_path: str, **context):
        """Process model name and parameters, return a configured Pydantic AI model instance.

        Args:
            value: User-friendly model name with optional parameters (e.g., 'sonnet (thinking)', 'gpt-4o (thinking=true)')
            vault_path: Path to vault (not used for model directive)
            **context: Additional context (not used for model directive)

        Returns:
            Configured Pydantic AI model instance ready for agent creation,
            or a ModelExecutionSpec in skip mode for aliases like 'none'

        Raises:
            ValueError: If model name is not recognized or model creation fails
        """
        if DirectiveValueParser.is_empty(value):
            raise ValueError("Model name cannot be empty")

        # Parse model name and parameters
        model_name, parameters = DirectiveValueParser.parse_value_with_parameters(
            value, allowed_parameters={"thinking"}
        )
        normalized_model = DirectiveValueParser.normalize_string(model_name, to_lower=True)

        execution = resolve_model_execution_spec(value)
        if execution.mode == "skip":
            return execution

        # Special case: test model (hardcoded for validation, not in mappings)
        if normalized_model == 'test':
            return TestModel()

        # Validate API keys for this model
        validate_api_keys(normalized_model)
        
        # Resolve model name to provider and model string
        provider, model_string = resolve_model(normalized_model)
        
        # Parse thinking parameter
        enable_thinking = False
        if 'thinking' in parameters:
            thinking_value = parameters['thinking'].lower()
            enable_thinking = thinking_value == 'true'

        # Create models with provider-specific settings
        if provider == 'google':
            settings_kwargs = {"timeout": get_default_api_timeout()}
            max_output_tokens = get_default_max_output_tokens()
            if max_output_tokens > 0:
                settings_kwargs["max_tokens"] = max_output_tokens
            # Keep thinking toggles disabled by default; callers can opt-in once configs stabilize.
            api_key = get_secret_value('GOOGLE_API_KEY')
            return GoogleModel(
                model_string,
                provider=GoogleProvider(api_key=api_key),
                settings=GoogleModelSettings(**settings_kwargs)
            )

        elif provider == 'anthropic':
            settings_kwargs = {"timeout": get_default_api_timeout()}
            max_output_tokens = get_default_max_output_tokens()
            if max_output_tokens > 0:
                settings_kwargs["max_tokens"] = max_output_tokens
            if enable_thinking:
                settings_kwargs["anthropic_thinking"] = {
                    "type": "enabled",
                    "budget_tokens": 2000
                }
            api_key = get_secret_value('ANTHROPIC_API_KEY')
            return AnthropicModel(
                model_string,
                provider=AnthropicProvider(api_key=api_key),
                settings=AnthropicModelSettings(**settings_kwargs)
            )

        elif provider == 'openai':
            settings_kwargs = {"timeout": get_default_api_timeout()}
            max_output_tokens = get_default_max_output_tokens()
            if max_output_tokens > 0:
                settings_kwargs["max_tokens"] = max_output_tokens
            # if not enable_thinking:
            #     # OpenAI reasoning models always use reasoning, set to minimum effort
            #     # settings_kwargs["openai_reasoning_effort"] = "minimal"
            #     # settings_kwargs["openai_reasoning_summary"] = "auto"
            #     pass
            # elif enable_thinking:
            #     settings_kwargs["openai_reasoning_effort"] = "high"
            #     settings_kwargs["openai_reasoning_summary"] = "auto"
            provider_config = get_provider_config(provider)
            api_key = self._resolve_config_value(provider_config.get('api_key'))
            base_url = self._resolve_config_value(provider_config.get('base_url'))
            return OpenAIResponsesModel(
                model_string,
                provider=OpenAIProvider(api_key=api_key, base_url=base_url),
                settings=OpenAIResponsesModelSettings(**settings_kwargs),
            )

        elif provider == 'grok':
            settings_kwargs = {"timeout": get_default_api_timeout()}
            max_output_tokens = get_default_max_output_tokens()
            if max_output_tokens > 0:
                settings_kwargs["max_tokens"] = max_output_tokens
            api_key = get_secret_value('GROK_API_KEY')
            return OpenAIModel(
                model_string,
                provider=GrokProvider(api_key=api_key),
                settings=OpenAIResponsesModelSettings(**settings_kwargs)
            )

        elif provider == 'mistral':
            settings_kwargs = {"timeout": get_default_api_timeout()}
            max_output_tokens = get_default_max_output_tokens()
            if max_output_tokens > 0:
                settings_kwargs["max_tokens"] = max_output_tokens
            api_key = get_secret_value('MISTRAL_API_KEY')
            return MistralModel(
                model_string,
                provider=MistralProvider(api_key=api_key),
                settings=ModelSettings(**settings_kwargs)
            )

        else:
            # Any other provider is treated as OpenAI-compatible endpoint
            # (Ollama, LM Studio, vLLM, etc.)
            provider_config = get_provider_config(provider)
            base_url_config = provider_config.get('base_url')

            if not base_url_config:
                raise ValueError(
                    f"Provider '{provider}' requires 'base_url' to be configured in system/settings.yaml. "
                    f"Set providers.{provider}.base_url to a literal URL or the name of a stored secret."
                )

            # Look up in secrets store first, fall back to literal value
            base_url = self._resolve_config_value(base_url_config)

            settings_kwargs = {"timeout": get_default_api_timeout()}
            max_output_tokens = get_default_max_output_tokens()
            if max_output_tokens > 0:
                settings_kwargs["max_tokens"] = max_output_tokens

            api_key = self._resolve_config_value(provider_config.get('api_key'))
            return OpenAIModel(
                model_string,
                provider=OpenAIProvider(api_key=api_key, base_url=base_url),
                settings=ModelSettings(**settings_kwargs)
            )
