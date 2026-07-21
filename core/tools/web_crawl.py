"""Stable web crawl tool with settings-selected strategy."""

from __future__ import annotations

import time

from pydantic_ai.tools import Tool

from core.tools.base import BaseTool
from core.tools.web_common import log_web_capability_completed, web_tool_failure
from core.web.config import get_web_strategy_name
from core.web.service import WebCapabilityService


class WebCrawl(BaseTool):
    """Provider-neutral website crawl tool."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        del vault_path
        service = WebCapabilityService()

        async def web_crawl(
            *,
            url: str,
            instructions: str = "Find comprehensive information and documentation",
            max_depth: int = 1,
            max_pages: int = 10,
            allow_external: bool = False,
        ) -> str:
            """Crawl related pages from a starting URL.

            :param url: Starting URL
            :param instructions: Description of relevant content
            :param max_depth: Maximum link depth, from 1 to 5
            :param max_pages: Maximum pages, from 1 to 50
            :param allow_external: Whether links on other domains may be followed
            """
            strategy = get_web_strategy_name("web_crawl")
            started_at = time.monotonic()
            try:
                result = await service.crawl(
                    url=url,
                    instructions=instructions,
                    max_depth=max_depth,
                    max_pages=max_pages,
                    allow_external=allow_external,
                    strategy=strategy,
                )
                if not result.pages:
                    reason = (
                        result.failures[0].error
                        if result.failures
                        else "No pages were crawled"
                    )
                    raise RuntimeError(reason)
            except Exception as exc:  # noqa: BLE001 - tool boundary
                return web_tool_failure(
                    tool_name="web_crawl",
                    strategy=strategy,
                    exc=exc,
                    phase="web_crawl",
                    urls=[url],
                )
            log_web_capability_completed(
                tool_name="web_crawl",
                strategy=result.strategy,
                result_count=len(result.pages),
                duration_seconds=time.monotonic() - started_at,
                failure_count=len(result.failures),
            )
            sections = [
                "# Website Crawl Results",
                f"**Base URL:** {result.base_url}",
                f"**Pages Crawled:** {len(result.pages)}",
            ]
            sections.extend(
                f"## Page {index}: {page.effective_url}\n\n{page.content}"
                for index, page in enumerate(result.pages, 1)
            )
            if result.failures:
                sections.append(
                    "## Pages not crawled\n\n"
                    + "\n".join(
                        f"- {failure.source_url}: {failure.error}"
                        for failure in result.failures
                    )
                )
            return "\n\n".join(sections)

        return Tool(
            web_crawl,
            name="web_crawl",
            description=(
                "Explore related pages across a website using the configured crawl strategy."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        return """
Full documentation:
- `__virtual_docs__/tools/web_crawl.md`
"""
