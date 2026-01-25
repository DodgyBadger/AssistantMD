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


class BasicHaikuScenario(BaseScenario):
    """Test basic single-step workflow execution."""

    async def test_scenario(self):
        """Execute complete end-to-end workflow: system startup → workflow execution."""

        # === SETUP ===
        vault = self.create_vault("HaikuVault")

        # Create simple single-step workflow
        self.create_file(vault, "AssistantMD/Workflows/haiku_writer.md", HAIKU_WRITER_WORKFLOW)

        # === SYSTEM STARTUP VALIDATION ===
        # Test real system startup with vault discovery and job scheduling
        checkpoint = self.event_checkpoint()
        await self.start_system()

        # Validate system startup completed correctly
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "HaikuVault/haiku_writer"},
        )
        job_event = self.assert_event_contains(
            events,
            name="job_synced",
            expected={"job_id": "HaikuVault__haiku_writer", "action": "created"},
        )
        trigger = str(job_event.get("data", {}).get("trigger", "")).lower()
        assert "cron" in trigger, "Expected cron trigger"

        # === SCHEDULED WORKFLOW EXECUTION ===
        # Set a known date for predictable output file naming
        self.set_date("2025-01-15")  # Wednesday

        # Trigger the scheduled job and wait for completion
        checkpoint = self.event_checkpoint()
        assert await self.trigger_job(vault, "haiku_writer"), (
            "Job should execute when triggered"
        )
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="job_executed",
            expected={"job_id": "HaikuVault__haiku_writer"},
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
