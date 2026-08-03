"""Stable web extraction tool with settings-selected strategy."""

from __future__ import annotations

import time

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.tools.base import BaseTool
from core.tools.web_common import log_web_capability_completed, web_tool_failure
from core.web.config import get_web_strategy_name
from core.web.service import WebCapabilityService


class WebExtract(BaseTool):
    """Provider-neutral URL extraction tool."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        del vault_path
        service = WebCapabilityService()

        async def web_extract(
            *, urls: str | list[str], include_images: bool = False
        ) -> str | ToolReturn:
            """Extract content from one or more known URLs.

            :param urls: One URL or a list of up to ten URLs
            :param include_images: Whether the selected strategy should return image metadata
            """
            normalized_urls = [urls] if isinstance(urls, str) else list(urls)
            strategy = get_web_strategy_name("web_extract")
            started_at = time.monotonic()
            try:
                result = await service.extract(
                    urls=normalized_urls,
                    include_images=include_images,
                    strategy=strategy,
                )
                if not result.items:
                    reason = (
                        result.failures[0].error
                        if result.failures
                        else "No content was extracted"
                    )
                    raise RuntimeError(reason)
            except Exception as exc:  # noqa: BLE001 - tool boundary
                return web_tool_failure(
                    tool_name="web_extract",
                    strategy=strategy,
                    exc=exc,
                    phase="web_extract",
                    urls=normalized_urls,
                )
            log_web_capability_completed(
                tool_name="web_extract",
                strategy=result.strategy,
                result_count=len(result.items),
                duration_seconds=time.monotonic() - started_at,
                failure_count=len(result.failures),
            )
            sections: list[str] = []
            for item in result.items:
                section = f"# Content from {item.effective_url}\n\n{item.content}"
                if item.images:
                    section += "\n\n## Images\n\n" + "\n".join(
                        f"- {image_url}" for image_url in item.images
                    )
                sections.append(section)
            if result.failures:
                sections.append(
                    "## URLs not extracted\n\n"
                    + "\n".join(
                        f"- {failure.source_url}: {failure.error}"
                        for failure in result.failures
                    )
                )
            return "\n\n".join(sections)

        return Tool(
            web_extract,
            name="web_extract",
            description=(
                "Extract readable content from known web page URLs using the configured "
                "strategy. This retrieves content transiently and does not import it into the vault."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        return """
Full documentation:
- `__virtual_docs__/tools/web_extract.md`
"""
