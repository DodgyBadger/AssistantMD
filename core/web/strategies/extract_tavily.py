"""Tavily extraction strategy."""

from __future__ import annotations

import asyncio

from tavily import TavilyClient

from core.settings import get_default_api_timeout
from core.settings.secrets_store import get_secret_value
from core.web.errors import WebStrategyConfigurationError
from core.web.models import (
    WebExtractionItem,
    WebExtractionResult,
    WebItemFailure,
)


async def extract_with_tavily(
    *,
    urls: list[str],
    include_images: bool,
) -> WebExtractionResult:
    """Extract one or more URLs through Tavily."""
    api_key = get_secret_value("TAVILY_API_KEY")
    if not api_key:
        raise WebStrategyConfigurationError(
            "Tavily extraction requires the TAVILY_API_KEY secret"
        )
    client = TavilyClient(api_key=api_key)
    payload = await asyncio.to_thread(
        client.extract,
        urls=urls,
        format="markdown",
        extract_depth="basic",
        include_images=include_images,
        timeout=min(int(get_default_api_timeout()), 120),
    )
    items = [
        WebExtractionItem(
            source_url=str(item.get("url") or ""),
            effective_url=str(item.get("url") or ""),
            content=str(item.get("raw_content") or ""),
            images=[str(value) for value in item.get("images", [])],
        )
        for item in payload.get("results", [])
        if isinstance(item, dict) and item.get("url") and item.get("raw_content")
    ]
    failures = [
        WebItemFailure(
            source_url=str(item.get("url") or "unknown"),
            error=str(item.get("error") or "Tavily could not extract content"),
            error_type="ProviderItemError",
        )
        for item in payload.get("failed_results", [])
        if isinstance(item, dict)
    ]
    returned_urls = {item.source_url for item in items} | {
        failure.source_url for failure in failures
    }
    failures.extend(
        WebItemFailure(
            source_url=url,
            error="Tavily returned no result for URL",
            error_type="ProviderItemError",
        )
        for url in urls
        if url not in returned_urls
    )
    return WebExtractionResult(
        strategy="tavily",
        items=items,
        failures=failures,
        metadata={"response_time": payload.get("response_time")},
    )
