"""
Integration scenario that exercises every configured tool using TestModel.

Runs a multi-step workflow where each step enables a single tool so we can
confirm tool wiring without external API calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ToolSuiteScenario(BaseScenario):
    """Validate that every tool can be invoked successfully with TestModel."""

    async def test_scenario(self):
        vault = self.create_vault("ToolSuiteVault")

        # Seed workflow that contains one step per tool
        self.copy_files(
            "validation/templates/AssistantMD/Workflows/tool-suite-validation.md",
            vault,
            "AssistantMD/Workflows",
            dest_filename="tool_suite.md",
        )

        await self.start_system()

        self.expect_vault_discovered("ToolSuiteVault")
        self.expect_workflow_loaded("ToolSuiteVault", "tool_suite")

        # Run with deterministic date for pattern placeholders if used later
        self.set_date("2025-01-06")  # Monday

        result = await self.run_workflow(vault, "tool_suite")
        self.expect_equals(result.status, "completed", "Tool suite workflow should finish successfully")

        expected_outputs = [
            "tool-outputs/documentation-access.md",
            "tool-outputs/file-ops-safe.md",
            "tool-outputs/file-ops-unsafe.md",
            "tool-outputs/web-search-duckduckgo.md",
            "tool-outputs/web-search-tavily.md",
            "tool-outputs/tavily-extract.md",
            "tool-outputs/tavily-crawl.md",
            "tool-outputs/code-execution.md",
        ]

        for relative_path in expected_outputs:
            self.expect_file_created(vault, relative_path)

        await self.stop_system()
        self.teardown_scenario()
