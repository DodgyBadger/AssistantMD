"""
Model creation and resolution for user-friendly model selection.

Maps simple model names (e.g., 'sonnet', 'gpt-4o') to provider-specific model objects
and handles environment-based configuration and API key validation.
"""

from threading import Lock
from typing import Dict, Tuple, Any

from core.logger import UnifiedLogger
from core.llm.model_selection import resolve_model_execution_spec
from core.settings.store import get_models_config, get_providers_config
from core.settings.secrets_store import get_secret_value, secret_has_value, load_secrets

# Create module logger
logger = UnifiedLogger(tag="models")

_MODEL_CACHE_LOCK = Lock()
MODEL_MAPPINGS: Dict[str, Tuple[str, str]] = {}
MODEL_CAPABILITIES: Dict[str, set[str]] = {}
PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {}


#######################################################################
## Model Mappings from YAML Configuration
#######################################################################

def _get_model_mappings() -> Dict[str, Tuple[str, str]]:
    """Get model mappings in the format expected by existing code."""
    models = get_models_config()

    mappings: Dict[str, Tuple[str, str]] = {}
    for model_name, model_config in models.items():
        if hasattr(model_config, "provider"):
            provider = model_config.provider
            model_string = model_config.model_string
        else:
            provider = model_config["provider"]
            model_string = model_config["model_string"]
        mappings[model_name] = (provider, model_string)

    return mappings


def _get_model_capabilities() -> Dict[str, set[str]]:
    """Get model capabilities with normalized lowercase values."""
    models = get_models_config()
    capabilities_map: Dict[str, set[str]] = {}

    for model_name, model_config in models.items():
        if hasattr(model_config, "capabilities"):
            capabilities = list(model_config.capabilities or ["text"])
        else:
            capabilities = list(model_config.get("capabilities", ["text"]))
        normalized = {
            str(capability).strip().lower()
            for capability in capabilities
            if str(capability).strip()
        }
        if not normalized:
            normalized = {"text"}
        capabilities_map[model_name.lower().strip()] = normalized

    return capabilities_map


def _get_provider_configs() -> Dict[str, Dict[str, Any]]:
    """Get full provider configurations from YAML configuration.

    Returns complete provider configs, allowing access to any configured
    key/value pairs (api_key, base_url, etc.) without parser changes.
    """
    providers = get_providers_config()
    config_map: Dict[str, Dict[str, Any]] = {}

    for name, provider_config in providers.items():
        if hasattr(provider_config, "model_dump"):
            config_map[name] = provider_config.model_dump()
        else:
            config_map[name] = provider_config

    return config_map


def _refresh_model_cache_unlocked() -> None:
    """Refresh module-level caches for model/provider mappings."""
    global MODEL_MAPPINGS, MODEL_CAPABILITIES, PROVIDER_CONFIGS
    MODEL_MAPPINGS = _get_model_mappings()
    MODEL_CAPABILITIES = _get_model_capabilities()
    PROVIDER_CONFIGS = _get_provider_configs()


def refresh_model_cache() -> None:
    """Public helper to refresh cached model/provider mappings."""
    with _MODEL_CACHE_LOCK:
        _refresh_model_cache_unlocked()


# Initialise cache on import so that lookups work immediately.
_refresh_model_cache_unlocked()


#######################################################################
## Model Resolution Functions
#######################################################################

def resolve_model(model_name: str) -> Tuple[str, str]:
    """
    Resolve user-friendly model name to provider and model string.
    
    Args:
        model_name: User-friendly model name (case-insensitive)
        
    Returns:
        Tuple of (provider, model_string)
        
    Raises:
        ValueError: If model name is not recognized
    """
    # Case-insensitive lookup
    model_key = model_name.lower().strip()
    
    if model_key not in MODEL_MAPPINGS:
        available_models = ', '.join(sorted(MODEL_MAPPINGS.keys()))
        raise ValueError(
            f"Unknown model '{model_name}'. Available models: {available_models}"
        )
    
    return MODEL_MAPPINGS[model_key]


def get_provider_config(provider: str) -> Dict[str, Any]:
    """Get full configuration for a provider.

    Returns all configured key/value pairs for the provider.
    Allows client code to access any setting without parser changes.

    Args:
        provider: Provider name (e.g., 'google', 'anthropic', 'custom')

    Returns:
        Dictionary with all provider configuration keys
    """
    return PROVIDER_CONFIGS.get(provider, {})


def _has_resolved_base_url(provider_config: Dict[str, Any]) -> bool:
    """Return True when provider base_url is configured as secret value or literal URL."""
    raw_base_url = provider_config.get("base_url")
    if not isinstance(raw_base_url, str):
        return False

    base_url = raw_base_url.strip()
    if not base_url or base_url.lower() == "null":
        return False

    # Secret-backed base_url (preferred)
    if get_secret_value(base_url):
        return True

    # Literal URLs are also valid configuration.
    return "://" in base_url


def get_model_capabilities(model_name: str) -> set[str]:
    """Return normalized capability set for a model alias."""
    model_key = model_name.lower().strip()
    if model_key not in MODEL_MAPPINGS:
        available_models = ", ".join(sorted(MODEL_MAPPINGS.keys()))
        raise ValueError(
            f"Unknown model '{model_name}'. Available models: {available_models}"
        )
    return set(MODEL_CAPABILITIES.get(model_key, {"text"}))


def model_supports_capability(model_name: str, capability: str) -> bool:
    """Return True when model alias includes the requested capability."""
    requested = capability.lower().strip()
    if not requested:
        return False
    execution = resolve_model_execution_spec(model_name)
    if execution.mode == "skip" or not execution.base_alias:
        return False
    return requested in get_model_capabilities(model_name)


def validate_api_keys(model_name: str) -> None:
    """
    Validate that required API key exists for the specified model.

    Args:
        model_name: User-friendly model name

    Raises:
        ValueError: If required API key is missing
    """
    provider, _ = resolve_model(model_name)
    provider_config = get_provider_config(provider)
    required_key = provider_config.get('api_key')

    # No API key required (test model, custom endpoints, etc.)
    if required_key is None or required_key == 'null':
        return

    if not secret_has_value(required_key):
        # OpenAI-compatible providers can run against local/remote endpoints
        # that don't require authentication when base_url is configured.
        if _has_resolved_base_url(provider_config):
            return
        raise ValueError(
            f"Model '{model_name}' requires secret '{required_key}' to be configured. "
            f"Add this value via the Secrets configuration interface before using the {provider} provider."
        )


def get_available_api_keys() -> Dict[str, str]:
    """
    Get dictionary of available API keys from environment.

    Returns:
        Dictionary mapping API key names to their values (only for keys that are set)
    """
    secrets = load_secrets()
    available: Dict[str, str] = {}

    for provider_config in PROVIDER_CONFIGS.values():
        key_name = provider_config.get('api_key')
        if key_name and key_name != 'null':
            value = secrets.get(key_name)
            if value:
                available[key_name] = value

    return available
