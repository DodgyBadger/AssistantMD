"""Tavily crawl strategy."""

from __future__ import annotations

import asyncio

from tavily import TavilyClient  # type: ignore[import-untyped]

from core.settings import get_default_api_timeout
from core.settings.secrets_store import get_secret_value
from core.web.errors import WebStrategyConfigurationError
from core.web.models import WebCrawlResult, WebExtractionItem, WebItemFailure


async def crawl_with_tavily(
    *,
    url: str,
    instructions: str,
    max_depth: int,
    max_pages: int,
    allow_external: bool,
) -> WebCrawlResult:
    """Crawl a website through Tavily and normalize page results."""
    api_key = get_secret_value("TAVILY_API_KEY")
    if not api_key:
        raise WebStrategyConfigurationError(
            "Tavily crawl requires the TAVILY_API_KEY secret"
        )
    client = TavilyClient(api_key=api_key)
    payload = await asyncio.to_thread(
        client.crawl,
        url=url,
        instructions=instructions,
        max_depth=max_depth,
        max_breadth=min(max_pages, 50),
        limit=max_pages,
        extract_depth="basic",
        format="markdown",
        allow_external=allow_external,
        timeout=min(int(get_default_api_timeout()), 120),
    )
    pages = [
        WebExtractionItem(
            source_url=str(page.get("url") or ""),
            effective_url=str(page.get("url") or ""),
            content=str(page.get("raw_content") or ""),
        )
        for page in payload.get("results", [])
        if isinstance(page, dict) and page.get("url") and page.get("raw_content")
    ]
    failures = [
        WebItemFailure(
            source_url=str(page.get("url") or "unknown"),
            error=str(page.get("error") or "Tavily could not crawl page"),
            error_type="ProviderItemError",
        )
        for page in payload.get("failed_results", [])
        if isinstance(page, dict)
    ]
    return WebCrawlResult(
        strategy="tavily",
        base_url=str(payload.get("base_url") or url),
        pages=pages,
        failures=failures,
        metadata={"response_time": payload.get("response_time")},
    )
