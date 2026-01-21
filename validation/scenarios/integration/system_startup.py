"""
System startup validation scenario.

Tests core system functionality including:
- Job persistence across system restarts (SQLAlchemy job store)
- Job configuration change detection
- Real-time scheduled execution
- System discovery and loading processes
- Resilience to malformed workflow configurations
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class TestSystemStartupValidationScenario(BaseScenario):
    """Comprehensive system startup, shutdown, and persistence validation."""

    async def test_scenario(self):
        # Setup
        vault = self.create_vault("SystemTest")
        self.create_file(vault, "AssistantMD/Workflows/quick_job.md", QUICK_JOB_WORKFLOW)

        # Test subfolder support - create workflow in AssistantMD/Workflows/planning/ subfolder
        self.create_file(vault, "AssistantMD/Workflows/planning/quick_job_2.md", QUICK_JOB_2_WORKFLOW)

        # Test 1: System Discovery and Job Creation
        await self.start_system()

        self.expect_vault_discovered("SystemTest")
        self.expect_workflow_loaded("SystemTest", "quick_job")
        self.expect_scheduler_job_created("SystemTest/quick_job")

        # Validate subfolder workflow was discovered and loaded
        self.expect_workflow_loaded("SystemTest", "planning/quick_job_2")
        self.expect_scheduler_job_created("SystemTest/planning/quick_job_2")

        # Capture original job properties
        original_next_run = self.get_next_run_time(vault, "quick_job")
        original_trigger = self.get_job_trigger(vault, "quick_job")
        original_name = self.get_job_name(vault, "quick_job")

        # Capture subfolder job properties
        original_subfolder_next_run = self.get_next_run_time(vault, "planning/quick_job_2")
        original_subfolder_trigger = self.get_job_trigger(vault, "planning/quick_job_2")

        # Test 2: Job Persistence Across Restart
        await self.restart_system()

        restored_next_run = self.get_next_run_time(vault, "quick_job")
        restored_trigger = self.get_job_trigger(vault, "quick_job")
        restored_name = self.get_job_name(vault, "quick_job")

        self.expect_true(
            original_next_run == restored_next_run,
            "Next run time preserved across restart",
        )
        self.expect_true(
            str(original_trigger) == str(restored_trigger),
            "Trigger preserved across restart",
        )
        self.expect_true(
            original_name == restored_name,
            "Job name preserved across restart",
        )

        # Validate subfolder job also persists
        restored_subfolder_next_run = self.get_next_run_time(vault, "planning/quick_job_2")
        restored_subfolder_trigger = self.get_job_trigger(vault, "planning/quick_job_2")

        self.expect_true(
            original_subfolder_next_run == restored_subfolder_next_run,
            "Subfolder job next run time preserved",
        )
        self.expect_true(
            str(original_subfolder_trigger) == str(restored_subfolder_trigger),
            "Subfolder job trigger preserved",
        )

        # Test 3: Schedule Change Detection
        # Overwrite the original file with updated schedule (every 1m → every 2m)
        self.create_file(vault, "AssistantMD/Workflows/quick_job.md", QUICK_JOB_UPDATED_WORKFLOW)
        await self.restart_system()

        updated_next_run = self.get_next_run_time(vault, "quick_job")
        updated_trigger = self.get_job_trigger(vault, "quick_job")

        self.expect_true(
            str(original_trigger) != str(updated_trigger),
            "Trigger changed after schedule update",
        )
        self.expect_true(updated_next_run is not None, "Updated job should have next run time")

        # Test 4: Real-Time Scheduled Execution
        # Job runs every 2m (120s), so wait 150s to account for schedule + execution time
        execution_success = await self.wait_for_real_execution(vault, "quick_job", timeout=150)
        self.expect_true(execution_success, "Job should execute in real time via APScheduler")

        today_file = f"results/{datetime.now().strftime('%Y-%m-%d')}.md"
        self.expect_file_created(vault, today_file)

        # Test 5: Multiple Restart Cycle
        await self.restart_system()
        await self.restart_system()

        final_next_run = self.get_next_run_time(vault, "quick_job")
        self.expect_true(final_next_run is not None, "Job should survive multiple restarts")

        # Test 6: Malformed Workflow Resilience
        # Add a malformed workflow file with invalid schedule syntax
        self.create_file(vault, "AssistantMD/Workflows/malformed_schedule.md", MALFORMED_SCHEDULE_WORKFLOW)
        await self.restart_system()

        # Verify the system still started successfully
        self.expect_vault_discovered("SystemTest")

        # Verify good workflows are still loaded and working
        self.expect_workflow_loaded("SystemTest", "quick_job")
        self.expect_workflow_loaded("SystemTest", "planning/quick_job_2")
        self.expect_scheduler_job_created("SystemTest/quick_job")
        self.expect_scheduler_job_created("SystemTest/planning/quick_job_2")

        # Verify the malformed workflow error was captured
        self.expect_configuration_error("SystemTest", "malformed_schedule", "ValueError")

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

QUICK_JOB_WORKFLOW = """---
schedule: cron: */1 * * * *
workflow_engine: step
enabled: true
description: Quick job for persistence testing
---

## STEP1
@output-file results/{today}
@model test

Quick persistence test - creating file at scheduled intervals.
"""

QUICK_JOB_2_WORKFLOW = """---
schedule: cron: */2 * * * *
workflow_engine: step
enabled: true
description: Second quick job for subfolder testing
---

## STEP1
@output-file results/{today}
@model test

Quick subfolder test - creating file from subfolder workflow.
"""

QUICK_JOB_UPDATED_WORKFLOW = """---
schedule: cron: */2 * * * *
workflow_engine: step
enabled: true
description: Updated schedule for persistence testing
---

## STEP1
@output-file results/{today}
@model test

Updated persistence test - now running every 2 minutes.
"""

MALFORMED_SCHEDULE_WORKFLOW = """---
schedule: every 1d at 9am
workflow_engine: step
enabled: true
description: Malformed workflow with invalid old schedule syntax
---

## STEP1
@output-file test.md

This workflow has invalid schedule syntax (old format) and should fail to load without crashing the system.
"""
