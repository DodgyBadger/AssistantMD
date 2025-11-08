"""
Documentation builder scenario.

Exercises the documentation builder assistant to verify an LLM can
research the docs, generate a fresh assistant, repair a malformed
assistant, and produce user guidance.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class DocumentationBuilderScenario(BaseScenario):
    """Run the documentation builder assistant end-to-end."""

    async def test_scenario(self):
        """Execute setup → run → verification."""

        vault = self.create_vault("DocumentationBuilderVault")
        self.copy_files(
            "validation/templates/assistants/documentation_builder.md",
            vault,
            "assistants",
        )
        self.copy_files(
            "validation/templates/files/broken_assistant.md",
            vault,
            "inputs",
        )

        await self.start_system()
        self.expect_vault_discovered("DocumentationBuilderVault")
        self.expect_assistant_loaded(
            "DocumentationBuilderVault", "documentation_builder"
        )
        self.expect_scheduler_job_created(
            "DocumentationBuilderVault/documentation_builder"
        )

        self.set_date("2025-01-15")
        await self.trigger_job(vault, "documentation_builder")

        self.expect_scheduled_execution_success(
            vault, "documentation_builder"
        )

        # Verify expected artifacts
        self.expect_file_created(vault, "analysis/research.md")
        self.expect_file_created(vault, "outputs/generated_assistant.md")
        self.expect_file_created(vault, "outputs/fixed_assistant.md")
        self.expect_file_created(vault, "reports/user_summary.md")

        await self.stop_system()
        self.teardown_scenario()
