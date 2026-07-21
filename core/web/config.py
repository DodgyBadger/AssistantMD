"""Settings access for stable web capabilities and their strategies."""

from __future__ import annotations

from typing import cast

from core.settings.store import get_general_settings
from core.web.registry import WebCapability, web_strategy_registry
from core.web.strategies import register_builtin_web_strategies


_STRATEGY_SETTING_NAMES: dict[WebCapability, str] = {
    "web_search": "web_search_strategy",
    "web_extract": "web_extract_strategy",
    "web_crawl": "web_crawl_strategy",
}
_STRATEGY_DEFAULTS: dict[WebCapability, str] = {
    "web_search": "duckduckgo",
    "web_extract": "curl",
    "web_crawl": "tavily",
}


def get_web_strategy_name(capability: WebCapability) -> str:
    """Return the configured strategy identifier for one web capability."""
    entry = get_general_settings().get(_STRATEGY_SETTING_NAMES[capability])
    raw_value = getattr(entry, "value", None)
    normalized = str(raw_value or "").strip().lower()
    return normalized or _STRATEGY_DEFAULTS[capability]


def get_web_tool_strategy_requirements(tool_name: str) -> tuple[str, tuple[str, ...]]:
    """Return selected strategy metadata for a stable web tool name."""
    if tool_name not in _STRATEGY_SETTING_NAMES:
        return "", ()
    capability = cast(WebCapability, tool_name)
    register_builtin_web_strategies(web_strategy_registry)
    selected = get_web_strategy_name(capability)
    spec = web_strategy_registry.resolve(capability, selected)
    return spec.name, spec.required_secrets
