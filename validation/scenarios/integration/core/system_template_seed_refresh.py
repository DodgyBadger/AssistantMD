"""
Integration scenario for manual refresh of packaged system authoring seeds.

Validates that startup preserves existing system templates and the explicit
System / Misc refresh action upgrades generated copies without manual file
deletion from system/Authoring.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class SystemTemplateSeedRefreshScenario(BaseScenario):
    """Validate packaged system templates refresh through the explicit API."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        system_root = controller._system_root
        target = system_root / "Authoring" / "default.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("STALE GENERATED DEFAULT", encoding="utf-8")

        seed = Path("core/authoring/seed_templates/context/default.md")
        expected = seed.read_text(encoding="utf-8")

        await self.start_system()

        settings_response = self.call_api("/api/system/settings")
        self.soft_assert_equal(
            settings_response.status_code,
            200,
            "Settings fetch should succeed before repair",
        )
        settings_raw = yaml.safe_load(settings_response.json()["content"])
        settings_raw["providers"]["openrouter"].pop("provider", None)
        settings_raw["settings"].pop("openrouter_ignored_providers", None)
        update_settings_response = self.call_api(
            "/api/system/settings",
            method="PUT",
            data={"content": yaml.safe_dump(settings_raw, sort_keys=False)},
        )
        self.soft_assert_equal(
            update_settings_response.status_code,
            200,
            "Settings update should allow existing OpenRouter provider without routing block",
        )

        repair_response = self.call_api("/api/system/settings/repair", method="POST")
        self.soft_assert_equal(
            repair_response.status_code,
            200,
            "Settings repair should complete through the system API",
        )
        repaired_settings = yaml.safe_load(repair_response.json()["content"])
        self.soft_assert_equal(
            repaired_settings["providers"]["openrouter"].get("provider"),
            {"require_parameters": True},
            "Settings repair should restore OpenRouter provider routing defaults",
        )
        self.soft_assert_equal(
            repaired_settings["settings"]["openrouter_ignored_providers"].get("value"),
            ["azure"],
            "Settings repair should restore OpenRouter ignored-provider defaults",
        )

        self.soft_assert_equal(
            target.read_text(encoding="utf-8"),
            "STALE GENERATED DEFAULT",
            "Startup should preserve existing system authoring files",
        )

        response = self.call_api("/api/system/authoring/seed-refresh", method="POST")
        self.soft_assert_equal(
            response.status_code,
            200,
            "Manual refresh should complete through the system API",
        )
        payload = response.json()
        self.soft_assert(
            target.as_posix() in payload.get("updated", []),
            "Manual refresh should report the stale default template as updated",
        )
        self.soft_assert_equal(
            target.read_text(encoding="utf-8"),
            expected,
            "Manual refresh should update packaged system authoring seed files",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
