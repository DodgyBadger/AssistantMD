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
        assert "MultiToolVault" in self.get_discovered_vaults(), "Vault not discovered"
        workflows = self.get_loaded_workflows()
        assert any(
            cfg.global_id == "MultiToolVault/multi-tool-workflow" for cfg in workflows
        ), "Workflow not loaded"
        jobs = self.get_scheduler_jobs()
        assert any(
            job.job_id == "MultiToolVault__multi-tool-workflow" for job in jobs
        ), "Scheduler job not created"

        # === TOOL EXECUTION TESTS ===
        self.set_date("2025-01-21")  # Tuesday

        # Trigger all tool tests - the workflow has 6 steps, each will run
        await self.trigger_job(vault, "multi-tool-workflow")

        # === ASSERTIONS ===
        assert len(self.get_job_executions(vault, "multi-tool-workflow")) > 0, (
            "No executions recorded for MultiToolVault/multi-tool-workflow"
        )

        # Check that all output files were created
        output_files = [
            "tools/duckduckgo-test.md",
            "tools/tavily-test.md",
            "tools/piston-test.md",
            "tools/web-search-generic-test.md",
            "tools/code-execution-generic-test.md",
            "tools/tavily-extract-test.md",
            "tools/tavily-crawl-test.md",
        ]
        for rel_path in output_files:
            output_path = vault / rel_path
            assert output_path.exists(), f"Expected {rel_path} to be created"
            assert output_path.stat().st_size > 0, f"{rel_path} is empty"

        # Verify content in the tool outputs
        content_expectations = {
            "tools/duckduckgo-test.md": "Python",
            "tools/tavily-test.md": "machine learning",
            "tools/piston-test.md": "5",
            "tools/web-search-generic-test.md": "JavaScript",
            "tools/code-execution-generic-test.md": "56",
            "tools/tavily-extract-test.md": "Python",
            "tools/tavily-crawl-test.md": "Python",
        }
        for rel_path, expected in content_expectations.items():
            content = (vault / rel_path).read_text()
            assert expected in content, f"Expected '{expected}' in {rel_path}"

        # Clean up
        await self.stop_system()
        self.teardown_scenario()
