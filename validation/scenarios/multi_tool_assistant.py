"""
Multi-Tool Workflow scenario - tests all tool backends.

Tests each tool implementation separately including named backends and generic aliases.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class MultiToolWorkflowScenario(BaseScenario):
    """Test all tool backends and generic aliases independently."""

    async def test_scenario(self):
        """Execute multi-tool workflow testing all backends."""

        # === SETUP ===
        vault = self.create_vault("MultiToolVault")

        # Copy the multi-tool workflow template
        self.copy_files("validation/templates/AssistantMD/Workflows/multi-tool-workflow.md", vault, "AssistantMD/Workflows")

        # === SYSTEM STARTUP VALIDATION ===
        await self.start_system()

        # Validate system startup
        self.expect_vault_discovered("MultiToolVault")
        self.expect_workflow_loaded("MultiToolVault", "multi-tool-workflow")
        self.expect_scheduler_job_created("MultiToolVault/multi-tool-workflow")

        # === TOOL EXECUTION TESTS ===
        self.set_date("2025-01-21")  # Tuesday

        # Trigger all tool tests - the workflow has 6 steps, each will run
        await self.trigger_job(vault, "multi-tool-workflow")

        # === ASSERTIONS ===
        self.expect_scheduled_execution_success(vault, "multi-tool-workflow")

        # Check that all output files were created
        self.expect_file_created(vault, "tools/duckduckgo-test.md")
        self.expect_file_created(vault, "tools/tavily-test.md")
        self.expect_file_created(vault, "tools/librechat-test.md")
        self.expect_file_created(vault, "tools/web-search-generic-test.md")
        self.expect_file_created(vault, "tools/code-execution-generic-test.md")
        self.expect_file_created(vault, "tools/tavily-extract-test.md")
        self.expect_file_created(vault, "tools/tavily-crawl-test.md")

        # Verify content in the tool outputs
        self.expect_file_contains(vault, "tools/duckduckgo-test.md", ["Python"])
        self.expect_file_contains(vault, "tools/tavily-test.md", ["machine learning"])
        self.expect_file_contains(vault, "tools/librechat-test.md", ["5"])  # Length of list
        self.expect_file_contains(vault, "tools/web-search-generic-test.md", ["JavaScript"])
        self.expect_file_contains(vault, "tools/code-execution-generic-test.md", ["56"])  # 7 * 8 (now uses LibreChat)
        self.expect_file_contains(vault, "tools/tavily-extract-test.md", ["Python"])
        self.expect_file_contains(vault, "tools/tavily-crawl-test.md", ["Python"])

        # Clean up
        await self.stop_system()
        self.teardown_scenario()
