"""
Basic Haiku scenario - simplest possible real workflow test.

Tests single-step workflow execution with file output.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# No more path isolation monkey patches needed! CoreServices handles clean dependency injection.

from validation.core.base_scenario import BaseScenario


class TestBasicHaikuScenario(BaseScenario):
    """Test basic single-step workflow execution."""

    async def test_scenario(self):
        """Execute complete end-to-end workflow: system startup → workflow execution."""

        # === SETUP ===
        vault = self.create_vault("HaikuVault")

        # Create simple single-step workflow
        self.create_file(vault, "AssistantMD/Workflows/haiku_writer.md", HAIKU_WRITER_WORKFLOW)

        # === SYSTEM STARTUP VALIDATION ===
        # Test real system startup with vault discovery and job scheduling
        await self.start_system()

        # Validate system startup completed correctly
        assert "HaikuVault" in self.get_discovered_vaults(), "Vault not discovered"
        workflows = self.get_loaded_workflows()
        assert any(
            cfg.global_id == "HaikuVault/haiku_writer" for cfg in workflows
        ), "Workflow not loaded"
        jobs = self.get_scheduler_jobs()
        assert any(
            job.job_id == "HaikuVault__haiku_writer" for job in jobs
        ), "Scheduler job not created"
        job = next(
            (job for job in jobs if job.job_id == "HaikuVault__haiku_writer"),
            None,
        )
        assert job is not None, "Scheduler job not found for schedule check"
        assert "cron" in job.trigger.lower(), "Expected cron trigger"

        # === SCHEDULED WORKFLOW EXECUTION ===
        # Set a known date for predictable output file naming
        self.set_date("2025-01-15")  # Wednesday

        # Trigger the scheduled job and wait for completion
        await self.trigger_job(vault, "haiku_writer")

        # === ASSERTIONS ===
        # Verify the scheduled job executed successfully
        assert len(self.get_job_executions(vault, "haiku_writer")) > 0, (
            "No executions recorded for HaikuVault/haiku_writer"
        )

        # Check output file was created with content
        output_path = vault / "2025-01-15.md"
        assert output_path.exists(), "Expected 2025-01-15.md to be created"
        assert output_path.stat().st_size > 0, "Output file is empty"

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

HAIKU_WRITER_WORKFLOW = """---
schedule: cron: 0 9 * * *
workflow_engine: step
enabled: true
description: Simple haiku writing workflow
---

## STEP1
@model gpt-mini
@output-file {today}
@header My new haiku - {today}

Write a beautiful haiku about integration testing. Format it nicely with proper line breaks.
"""
