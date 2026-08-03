"""Provider-neutral dispatcher for web search, extraction, and crawl."""

from __future__ import annotations

from typing import cast

from core.settings.secrets_store import secret_has_value
from core.web.config import get_web_strategy_name
from core.web.errors import WebStrategyConfigurationError, WebUrlPolicyError
from core.web.models import (
    WebCrawlResult,
    WebExtractionResult,
    WebItemFailure,
    WebSearchResult,
)
from core.web.registry import WebCapability, WebStrategyRegistry, web_strategy_registry
from core.web.security import resolve_public_url
from core.web.strategies import register_builtin_web_strategies


class WebCapabilityService:
    """Dispatch stable web capabilities to one explicitly selected strategy."""

    def __init__(self, registry: WebStrategyRegistry | None = None) -> None:
        self.registry = registry or web_strategy_registry
        if registry is None:
            register_builtin_web_strategies(self.registry)

    def strategy_requirements(
        self, capability: WebCapability, strategy: str | None = None
    ) -> tuple[str, tuple[str, ...]]:
        """Return the resolved strategy and its required secret names."""
        selected = strategy or get_web_strategy_name(capability)
        spec = self.registry.resolve(capability, selected)
        return spec.name, spec.required_secrets

    def assert_available(
        self, capability: WebCapability, strategy: str | None = None
    ) -> str:
        """Fail clearly when a selected strategy is unavailable."""
        selected, required_secrets = self.strategy_requirements(capability, strategy)
        missing = [name for name in required_secrets if not secret_has_value(name)]
        if missing:
            raise WebStrategyConfigurationError(
                f"{capability} strategy '{selected}' requires secrets: {', '.join(missing)}"
            )
        return selected

    async def search(
        self,
        *,
        query: str,
        max_results: int = 3,
        strategy: str | None = None,
    ) -> WebSearchResult:
        """Search through exactly one configured strategy."""
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("Search query cannot be empty")
        selected = self.assert_available("web_search", strategy)
        spec = self.registry.resolve("web_search", selected)
        result = await spec.handler(
            query=normalized_query,
            max_results=max(1, min(int(max_results), 10)),
        )
        _assert_result_strategy(selected, result.strategy)
        return cast(WebSearchResult, result)

    async def extract(
        self,
        *,
        urls: str | list[str],
        include_images: bool = False,
        strategy: str | None = None,
    ) -> WebExtractionResult:
        """Extract URLs through exactly one configured strategy."""
        normalized_urls = _normalize_urls(urls)
        valid_urls: list[str] = []
        policy_failures: list[WebItemFailure] = []
        for url in normalized_urls:
            try:
                resolve_public_url(url)
            except WebUrlPolicyError as exc:
                policy_failures.append(
                    WebItemFailure(
                        source_url=url,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                )
            else:
                valid_urls.append(url)
        selected = self.assert_available("web_extract", strategy)
        if not valid_urls:
            return WebExtractionResult(
                strategy=selected,
                items=[],
                failures=policy_failures,
            )
        spec = self.registry.resolve("web_extract", selected)
        result = await spec.handler(
            urls=valid_urls,
            include_images=bool(include_images),
        )
        _assert_result_strategy(selected, result.strategy)
        if not policy_failures:
            return cast(WebExtractionResult, result)
        return WebExtractionResult(
            strategy=result.strategy,
            items=result.items,
            failures=[*policy_failures, *result.failures],
            metadata=result.metadata,
        )

    async def crawl(
        self,
        *,
        url: str,
        instructions: str = "Find comprehensive information and documentation",
        max_depth: int = 1,
        max_pages: int = 10,
        allow_external: bool = False,
        strategy: str | None = None,
    ) -> WebCrawlResult:
        """Crawl through exactly one configured strategy."""
        normalized_url = str(url or "").strip()
        if not normalized_url:
            raise ValueError("Crawl URL cannot be empty")
        resolve_public_url(normalized_url)
        selected = self.assert_available("web_crawl", strategy)
        spec = self.registry.resolve("web_crawl", selected)
        result = await spec.handler(
            url=normalized_url,
            instructions=str(instructions or "").strip(),
            max_depth=max(1, min(int(max_depth), 5)),
            max_pages=max(1, min(int(max_pages), 50)),
            allow_external=bool(allow_external),
        )
        _assert_result_strategy(selected, result.strategy)
        return cast(WebCrawlResult, result)


def _normalize_urls(urls: str | list[str]) -> list[str]:
    raw_urls = [urls] if isinstance(urls, str) else list(urls)
    normalized = [str(url).strip() for url in raw_urls if str(url).strip()]
    if not normalized:
        raise ValueError("At least one URL is required")
    if len(normalized) > 10:
        raise ValueError("At most 10 URLs may be extracted in one call")
    return normalized


def _assert_result_strategy(selected: str, reported: str) -> None:
    if selected != reported:
        raise RuntimeError(
            f"Web strategy '{selected}' returned mismatched identity '{reported}'"
        )
