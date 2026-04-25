"""
Integration scenario for startup refresh of packaged system authoring seeds.

Validates that system-generated templates are upgradeable without manual file
deletion from system/Authoring.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class SystemTemplateSeedRefreshScenario(BaseScenario):
    """Validate packaged system templates overwrite stale generated copies."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        system_root = controller._system_root
        target = system_root / "Authoring" / "default.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("STALE GENERATED DEFAULT", encoding="utf-8")

        seed = Path("core/authoring/seed_templates/context/default.md")
        expected = seed.read_text(encoding="utf-8")

        await self.start_system()

        self.soft_assert_equal(
            target.read_text(encoding="utf-8"),
            expected,
            "Startup should refresh packaged system authoring seed files",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
