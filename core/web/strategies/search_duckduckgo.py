"""DuckDuckGo search strategy."""

from __future__ import annotations

import asyncio

from ddgs import DDGS

from core.settings import get_default_api_timeout
from core.web.models import WebSearchItem, WebSearchResult


async def search_with_duckduckgo(*, query: str, max_results: int) -> WebSearchResult:
    """Search DuckDuckGo and normalize its result shape."""

    def run() -> list[dict[str, object]]:
        client = DDGS(timeout=int(get_default_api_timeout()))
        return list(
            client.text(
                query=query,
                max_results=max_results,
                region="us-en",
                safesearch="moderate",
            )
            or []
        )

    raw_results = await asyncio.to_thread(run)
    items = [
        WebSearchItem(
            title=str(item.get("title") or "Untitled result"),
            url=str(item.get("href") or ""),
            snippet=str(item.get("body") or ""),
        )
        for item in raw_results
        if item.get("href")
    ]
    return WebSearchResult(strategy="duckduckgo", query=query, items=items)
