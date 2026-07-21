"""Built-in web strategy registration."""

from __future__ import annotations

from core.web.registry import WebStrategyRegistry, web_strategy_registry
from core.web.strategies.extract_curl import extract_with_curl
from core.web.strategies.extract_tavily import extract_with_tavily
from core.web.strategies.search_duckduckgo import search_with_duckduckgo
from core.web.strategies.search_tavily import search_with_tavily
from core.web.strategies.crawl_tavily import crawl_with_tavily


def register_builtin_web_strategies(
    registry: WebStrategyRegistry = web_strategy_registry,
) -> None:
    """Register built-ins once for the supplied registry."""
    existing = {
        (capability, name)
        for capability in ("web_search", "web_extract", "web_crawl")
        for name in registry.names(capability)
    }
    registrations = (
        ("web_search", "duckduckgo", search_with_duckduckgo, ()),
        ("web_search", "tavily", search_with_tavily, ("TAVILY_API_KEY",)),
        ("web_extract", "curl", extract_with_curl, ()),
        ("web_extract", "tavily", extract_with_tavily, ("TAVILY_API_KEY",)),
        ("web_crawl", "tavily", crawl_with_tavily, ("TAVILY_API_KEY",)),
    )
    from core.web.registry import WebStrategySpec

    for capability, name, handler, required_secrets in registrations:
        if (capability, name) in existing:
            continue
        registry.register(
            WebStrategySpec(
                capability=capability,
                name=name,
                handler=handler,
                required_secrets=required_secrets,
            )
        )
