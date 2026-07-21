"""Capability-specific registry for web strategy implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from core.web.errors import WebStrategyConfigurationError


WebCapability = Literal["web_search", "web_extract", "web_crawl"]
StrategyHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class WebStrategySpec:
    """One named implementation for one stable web capability."""

    capability: WebCapability
    name: str
    handler: StrategyHandler
    required_secrets: tuple[str, ...] = ()


class WebStrategyRegistry:
    """Resolve strategy identifiers independently for each capability."""

    def __init__(self) -> None:
        self._strategies: dict[tuple[WebCapability, str], WebStrategySpec] = {}

    def register(self, spec: WebStrategySpec) -> None:
        key = (spec.capability, self._normalize_name(spec.name))
        if key in self._strategies:
            raise ValueError(
                f"Web strategy '{spec.name}' is already registered for {spec.capability}"
            )
        self._strategies[key] = spec

    def resolve(self, capability: WebCapability, name: str) -> WebStrategySpec:
        normalized = self._normalize_name(name)
        spec = self._strategies.get((capability, normalized))
        if spec is None:
            available = ", ".join(self.names(capability)) or "none"
            raise WebStrategyConfigurationError(
                f"Unknown {capability} strategy '{name}'. Available strategies: {available}."
            )
        return spec

    def names(self, capability: WebCapability) -> list[str]:
        return sorted(
            spec.name
            for (registered_capability, _), spec in self._strategies.items()
            if registered_capability == capability
        )

    @staticmethod
    def _normalize_name(name: str) -> str:
        return str(name or "").strip().lower()


web_strategy_registry = WebStrategyRegistry()
