"""
Integration scenario that exercises every configured tool using TestModel.

Runs a multi-step assistant where each step enables a single tool so we can
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

        # Seed assistant that contains one step per tool
        self.copy_files(
            "validation/templates/assistants/tool-suite-validation.md",
            vault,
            "assistants",
            dest_filename="tool_suite.md",
        )

        await self.start_system()

        self.expect_vault_discovered("ToolSuiteVault")
        self.expect_assistant_loaded("ToolSuiteVault", "tool_suite")

        # Run with deterministic date for pattern placeholders if used later
        self.set_date("2025-01-06")  # Monday

        result = await self.run_assistant(vault, "tool_suite")
        self.expect_equals(result.status, "completed", "Tool suite assistant should finish successfully")

        expected_outputs = {
            "tool-outputs/documentation-access.md": ["read_documentation"],
            "tool-outputs/file-ops-safe.md": ["file_operations"],
            "tool-outputs/file-ops-unsafe.md": ["file_ops_unsafe"],
            "tool-outputs/web-search-duckduckgo.md": ["search_web_duckduckgo"],
            "tool-outputs/web-search-tavily.md": ["search_web_tavily"],
            "tool-outputs/tavily-extract.md": ["tavily_extract"],
            "tool-outputs/tavily-crawl.md": ["tavily_crawl"],
            "tool-outputs/code-execution.md": ["execute_code"],
        }

        for relative_path, keywords in expected_outputs.items():
            self.expect_file_created(vault, relative_path)
            self.expect_file_contains(vault, relative_path, keywords)

        await self.stop_system()
        self.teardown_scenario()
