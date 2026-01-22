"""
Documentation builder scenario.

Exercises the documentation builder workflow to verify an LLM can
research the docs, generate a fresh workflow, repair a malformed
workflow, and produce user guidance.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class DocumentationBuilderScenario(BaseScenario):
    """Run the documentation builder workflow end-to-end."""

    async def test_scenario(self):
        """Execute setup → run → verification."""

        vault = self.create_vault("DocumentationBuilderVault")
        self.copy_files(
            "validation/templates/AssistantMD/Workflows/documentation_builder.md",
            vault,
            "AssistantMD/Workflows",
        )
        self.copy_files(
            "validation/templates/files/broken_workflow.md",
            vault,
            "inputs",
        )

        await self.start_system()
        assert "DocumentationBuilderVault" in self.get_discovered_vaults(), (
            "Vault not discovered"
        )
        workflows = self.get_loaded_workflows()
        assert any(
            cfg.global_id == "DocumentationBuilderVault/documentation_builder"
            for cfg in workflows
        ), "Workflow not loaded"
        jobs = self.get_scheduler_jobs()
        assert any(
            job.job_id == "DocumentationBuilderVault__documentation_builder"
            for job in jobs
        ), "Scheduler job not created"

        self.set_date("2025-01-15")
        await self.trigger_job(vault, "documentation_builder")

        assert len(self.get_job_executions(vault, "documentation_builder")) > 0, (
            "No executions recorded for DocumentationBuilderVault/documentation_builder"
        )

        # Verify expected artifacts
        for rel_path in [
            "analysis/research.md",
            "outputs/generated_workflow.md",
            "outputs/fixed_workflow.md",
            "reports/user_summary.md",
        ]:
            output_path = vault / rel_path
            assert output_path.exists(), f"Expected {rel_path} to be created"
            assert output_path.stat().st_size > 0, f"{rel_path} is empty"

        await self.stop_system()
        self.teardown_scenario()
