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
        """Execute complete end-to-end workflow: system startup → assistant execution."""

        # === SETUP ===
        vault = self.create_vault("HaikuVault")

        # Create simple single-step assistant
        self.create_file(vault, "assistants/haiku_writer.md", HAIKU_WRITER_ASSISTANT)

        # === SYSTEM STARTUP VALIDATION ===
        # Test real system startup with vault discovery and job scheduling
        await self.start_system()

        # Validate system startup completed correctly
        self.expect_vault_discovered("HaikuVault")
        self.expect_assistant_loaded("HaikuVault", "haiku_writer")
        self.expect_scheduler_job_created("HaikuVault/haiku_writer")
        self.expect_schedule_parsed_correctly("HaikuVault/haiku_writer", "cron")

        # === SCHEDULED WORKFLOW EXECUTION ===
        # Set a known date for predictable output file naming
        self.set_date("2025-01-15")  # Wednesday

        # Trigger the scheduled job and wait for completion
        await self.trigger_job(vault, "haiku_writer")

        # === ASSERTIONS ===
        # Verify the scheduled job executed successfully
        self.expect_scheduled_execution_success(vault, "haiku_writer")

        # Check output file was created with content
        self.expect_file_created(vault, "2025-01-15.md")

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === ASSISTANT TEMPLATES ===

HAIKU_WRITER_ASSISTANT = """---
schedule: cron: 0 9 * * *
workflow: step
enabled: true
description: Simple haiku writing assistant
---

## STEP1
@model haiku
@output-file {today}
@header My new haiku - {today}

Write a beautiful haiku about integration testing. Format it nicely with proper line breaks.
"""