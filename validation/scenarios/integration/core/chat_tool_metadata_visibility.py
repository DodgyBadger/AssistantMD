"""
Integration scenario validating chat tool metadata hides compatibility-only tools.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ChatToolMetadataVisibilityScenario(BaseScenario):
    """Validate chat metadata exposes cache-era tools and hides buffer-era compatibility tools."""

    async def test_scenario(self):
        self.create_vault("ChatToolMetadataVisibilityVault")

        await self.start_system()
        try:
            response = self.call_api("/api/metadata")
            assert response.status_code == 200, "Metadata endpoint should succeed"
            payload = response.json()
            tool_names = {tool.get("name") for tool in payload.get("tools", [])}

            self.soft_assert(
                "code_execution_local" in tool_names,
                "Chat metadata should expose code_execution_local",
            )
            self.soft_assert(
                "buffer_ops" not in tool_names,
                "Chat metadata should hide buffer_ops because it is compatibility-only for chat",
            )
        finally:
            await self.stop_system()
            self.teardown_scenario()
