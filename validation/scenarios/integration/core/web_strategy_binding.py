"""Validate strategy-aware availability through shared tool binding."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.authoring.shared.tool_binding import resolve_tool_binding
from core.settings import validate_settings
from validation.core.base_scenario import BaseScenario


class WebStrategyBindingScenario(BaseScenario):
    """Prove provider requirements apply across settings-backed tool binding."""

    async def test_scenario(self) -> None:
        vault = self.create_vault("WebStrategyBindingVault")
        await self.start_system()
        original_secrets_path = os.environ.get("SECRETS_PATH")
        isolated_secrets = self.run_path / "isolated-secrets.yaml"
        isolated_secrets.write_text("", encoding="utf-8")
        os.environ["SECRETS_PATH"] = str(isolated_secrets)
        try:
            baseline = resolve_tool_binding(
                ["web_search", "web_extract"], vault_path=str(vault)
            )
            self.soft_assert_equal(
                baseline.tool_names(),
                ["web_search", "web_extract"],
                "Secret-free default web strategies should bind",
            )

            crawl = resolve_tool_binding(["web_crawl"], vault_path=str(vault))
            self.soft_assert_equal(
                crawl.tool_names(),
                [],
                "Tavily crawl should be unavailable without its selected strategy secret",
            )
            self.soft_assert(
                "TAVILY_API_KEY" in crawl.tool_instructions,
                "Skipped strategy should identify its missing secret",
            )

            update = self.call_api(
                "/api/system/settings/general/web_extract_strategy",
                method="PUT",
                data={"value": "tavily"},
            )
            self.soft_assert_equal(
                update.status_code,
                200,
                "Web extraction strategy should be user configurable",
            )
            tavily_extract = resolve_tool_binding(
                ["web_extract"], vault_path=str(vault)
            )
            self.soft_assert_equal(
                tavily_extract.tool_names(),
                [],
                "A Tavily-selected extraction capability should not fall back to curl",
            )
            self.soft_assert(
                "TAVILY_API_KEY" in tavily_extract.tool_instructions,
                "Tavily extraction unavailability should explain the missing secret",
            )

            status = validate_settings()
            self.soft_assert_equal(
                status.tool_availability.get("web_extract"),
                False,
                "Configuration health should mark the selected strategy unavailable",
            )
            matching_issue = next(
                (issue for issue in status.issues if issue.name == "tool:web_extract"),
                None,
            )
            self.soft_assert(
                matching_issue is not None
                and "strategy 'tavily'" in matching_issue.message,
                "Configuration health should identify the selected strategy",
            )
        finally:
            if original_secrets_path is None:
                os.environ.pop("SECRETS_PATH", None)
            else:
                os.environ["SECRETS_PATH"] = original_secrets_path
            await self.stop_system()
            self.teardown_scenario()
        self.assert_no_failures()
