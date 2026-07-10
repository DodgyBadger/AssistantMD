"""Validate app-wide enabled tool registry behavior."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class EnabledToolsRegistryScenario(BaseScenario):
    """Validate enabled_tools filters model/direct tool binding surfaces."""

    async def test_scenario(self) -> None:
        vault = self.create_vault("EnabledToolsRegistryVault")
        await self.start_system()
        try:
            update_response = self.call_api(
                "/api/system/settings/general/enabled_tools",
                method="PUT",
                data={
                    "value": json.dumps(
                        ["propose_file_edits", "review_create_file", "session_ops"]
                    )
                },
            )
            assert update_response.status_code == 200, "enabled_tools setting should update"

            metadata_response = self.call_api("/api/metadata")
            assert metadata_response.status_code == 200, "Metadata endpoint should succeed"
            metadata = metadata_response.json()
            assert metadata.get("settings", {}).get("enabled_tools") == [
                "session_ops"
            ], "Metadata should expose only resolved, non-retired enabled tools"
            assert (
                "default_chat_tools" not in metadata.get("settings", {})
            ), "Metadata should not expose removed default_chat_tools setting"

            from core.authoring.shared.tool_binding import resolve_tool_binding
            from core.settings.store import get_enabled_tool_names

            assert get_enabled_tool_names() == [
                "session_ops"
            ], "Enabled tool helper should preserve configured enabled order"

            binding = resolve_tool_binding(["session_ops"], vault_path=str(vault))
            assert binding.tool_names() == [
                "session_ops"
            ], "Enabled tools should bind normally"

            all_binding = resolve_tool_binding("all", vault_path=str(vault))
            assert all_binding.tool_names() == [
                "session_ops"
            ], "Binding all should resolve only app-wide enabled tools"

            try:
                resolve_tool_binding(["file_read"], vault_path=str(vault))
            except ValueError as exc:
                assert "unavailable or disabled" in str(exc)
            else:
                raise AssertionError("Disabled configured tools should fail clearly")
        finally:
            await self.stop_system()
            self.teardown_scenario()
