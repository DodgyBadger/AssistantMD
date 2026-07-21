"""Validate explicit web strategy dispatch and shared ingestion primitives."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.strategies.html_raw import extract_html_markdownify
from core.settings.upgrades import upgrade_settings_mapping
from core.web.errors import WebUrlPolicyError
from core.web.html import html_to_markdown
from core.web.models import WebSearchItem, WebSearchResult
from core.web.registry import WebStrategyRegistry, WebStrategySpec
from core.web.security import resolve_public_url, sanitize_url_for_log
from core.web.service import WebCapabilityService
from validation.core.base_scenario import BaseScenario


class WebCapabilityStrategiesScenario(BaseScenario):
    """Prove strategies are explicit and ingestion reuses conversion policy."""

    async def test_scenario(self) -> None:
        calls: list[str] = []
        registry = WebStrategyRegistry()

        async def selected_search(*, query: str, max_results: int) -> WebSearchResult:
            calls.append("selected")
            return WebSearchResult(
                strategy="selected",
                query=query,
                items=[
                    WebSearchItem(
                        title="Result",
                        url="https://example.com",
                        snippet=str(max_results),
                    )
                ],
            )

        async def fallback_search(**_kwargs) -> WebSearchResult:
            calls.append("fallback")
            raise AssertionError("Unselected strategy must not run")

        registry.register(WebStrategySpec("web_search", "selected", selected_search))
        registry.register(WebStrategySpec("web_search", "fallback", fallback_search))
        service = WebCapabilityService(registry)
        result = await service.search(
            query="assistantmd", max_results=4, strategy="selected"
        )
        self.soft_assert_equal(
            result.strategy, "selected", "Configured search strategy should be used"
        )
        self.soft_assert_equal(
            calls, ["selected"], "Dispatch should not invoke a fallback strategy"
        )

        try:
            await service.extract(urls="http://127.0.0.1/private", strategy="missing")
        except WebUrlPolicyError:
            pass
        else:
            self.soft_assert(
                False,
                "Public-target policy should run before extraction strategy dispatch",
            )

        html = (
            "<html><head><title>Shared</title></head><body><h1>Heading</h1>"
            "<script>ignored()</script></body></html>"
        )
        shared_markdown = html_to_markdown(html, clean_html=True)
        ingestion_markdown = extract_html_markdownify(
            RawDocument(
                source_uri="https://example.com/article",
                kind=SourceKind.URL,
                mime="text/html",
                payload=html,
            ),
            {"clean_html": True},
        ).plain_text
        self.soft_assert_equal(
            ingestion_markdown,
            shared_markdown,
            "URL ingestion should use the shared HTML conversion contract",
        )
        self.soft_assert(
            "ignored" not in ingestion_markdown,
            "Shared clean_html policy should remove script content",
        )

        try:
            resolve_public_url("http://127.0.0.1/private")
        except WebUrlPolicyError:
            pass
        else:
            self.soft_assert(False, "Private URL targets should be rejected")
        self.soft_assert_equal(
            sanitize_url_for_log(
                "https://user:password@example.com/article?token=secret#fragment"
            ),
            "https://example.com/article",
            "URL logs should omit credentials, query strings, and fragments",
        )

        upgraded = upgrade_settings_mapping(
            {
                "settings": {
                    "enabled_tools": {
                        "value": [
                            "web_search_tavily",
                            "tavily_extract",
                            "custom_tool",
                        ]
                    },
                    "ingestion_url_fetch_backend": {"value": "curl"},
                },
                "tools": {"custom_tool": {"user_editable": True}},
            },
            {
                "settings": {
                    "disabled_tools": {"value": []},
                    "web_search_strategy": {"value": "duckduckgo"},
                    "ingestion_url_fetch_strategy": {"value": "curl"},
                },
                "tools": {
                    "web_search": {},
                    "web_extract": {},
                    "web_crawl": {},
                    "file_read": {},
                },
            },
        )
        upgraded_settings = upgraded["settings"]
        self.soft_assert_equal(
            upgraded_settings["disabled_tools"]["value"],
            ["file_read"],
            "Settings upgrade should preserve the old allowlist as a denylist",
        )
        self.soft_assert(
            "enabled_tools" not in upgraded_settings,
            "Settings upgrade should remove the retired enabled_tools setting",
        )
        self.soft_assert_equal(
            upgraded_settings["web_search_strategy"]["value"],
            "tavily",
            "A single legacy search provider should preserve its strategy",
        )
        self.soft_assert_equal(
            upgraded_settings["ingestion_url_fetch_strategy"]["value"],
            "curl",
            "Ingestion fetch strategy should retain its configured value",
        )
        web_disabled = upgrade_settings_mapping(
            {"settings": {"enabled_tools": {"value": ["file_read"]}}},
            {
                "settings": {"disabled_tools": {"value": []}},
                "tools": {"web_search": {}, "file_read": {}},
            },
        )
        self.soft_assert_equal(
            web_disabled["settings"]["disabled_tools"]["value"],
            ["web_search"],
            "Settings upgrade should preserve tools excluded by the old allowlist",
        )
        malformed_allowlist = upgrade_settings_mapping(
            {"settings": {"enabled_tools": {"value": "not-a-list"}}},
            {
                "settings": {"disabled_tools": {"value": []}},
                "tools": {"web_search": {}, "file_read": {}},
            },
        )
        self.soft_assert_equal(
            malformed_allowlist["settings"]["disabled_tools"]["value"],
            ["web_search", "file_read"],
            "Malformed legacy allowlists should remain fail-closed during repair",
        )

        self.teardown_scenario()
        self.assert_no_failures()
