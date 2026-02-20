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


class SystemStartupScenario(BaseScenario):
    """Comprehensive system startup, shutdown, and persistence validation."""

    async def test_scenario(self):
        # Setup
        vault = self.create_vault("SystemTest")
        self.create_file(vault, "AssistantMD/Workflows/quick_job.md", QUICK_JOB_WORKFLOW)

        # Test subfolder support - create workflow in AssistantMD/Workflows/planning/ subfolder
        self.create_file(vault, "AssistantMD/Workflows/planning/quick_job_2.md", QUICK_JOB_2_WORKFLOW)

        # Test 1: System Discovery and Job Creation
        checkpoint = self.event_checkpoint()
        await self.start_system()

        events = self.events_since(checkpoint)
        checkpoint = self.event_checkpoint()
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "SystemTest/quick_job"},
        )
        self.assert_event_contains(
            events,
            name="job_synced",
            expected={"job_id": "SystemTest__quick_job", "action": "created"},
        )

        # Validate subfolder workflow was discovered and loaded
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "SystemTest/planning/quick_job_2"},
        )
        self.assert_event_contains(
            events,
            name="job_synced",
            expected={
                "job_id": "SystemTest__planning__quick_job_2",
                "action": "created",
            },
        )

        # Capture original job properties
        original_event = self.latest_event(
            events,
            name="job_synced",
            workflow_id="SystemTest/quick_job",
        )
        assert original_event is not None, "Missing job_synced event for quick_job"
        original_data = original_event.get("data", {})
        original_next_run = original_data.get("next_run_time")
        original_trigger = original_data.get("trigger")
        original_name = original_data.get("job_name")

        # Capture subfolder job properties
        original_subfolder_event = self.latest_event(
            events,
            name="job_synced",
            workflow_id="SystemTest/planning/quick_job_2",
        )
        assert original_subfolder_event is not None, "Missing job_synced event for quick_job_2"
        original_subfolder_data = original_subfolder_event.get("data", {})
        original_subfolder_next_run = original_subfolder_data.get("next_run_time")
        original_subfolder_trigger = original_subfolder_data.get("trigger")

        # Test 2: Job Persistence Across Restart
        await self.restart_system()

        new_events = self.events_since(checkpoint)
        checkpoint = self.event_checkpoint()

        restored_event = self.latest_event(
            new_events,
            name="job_synced",
            workflow_id="SystemTest/quick_job",
        )
        assert restored_event is not None, "Missing job_synced event after restart"
        restored_data = restored_event.get("data", {})
        restored_next_run = restored_data.get("next_run_time")
        restored_trigger = restored_data.get("trigger")
        restored_name = restored_data.get("job_name")

        assert original_next_run == restored_next_run, (
            "Next run time preserved across restart"
        )
        assert str(original_trigger) == str(restored_trigger), (
            "Trigger preserved across restart"
        )
        assert original_name == restored_name, "Job name preserved across restart"

        # Validate subfolder job also persists
        restored_subfolder_event = self.latest_event(
            new_events,
            name="job_synced",
            workflow_id="SystemTest/planning/quick_job_2",
        )
        assert restored_subfolder_event is not None, "Missing job_synced event for quick_job_2 after restart"
        restored_subfolder_data = restored_subfolder_event.get("data", {})
        restored_subfolder_next_run = restored_subfolder_data.get("next_run_time")
        restored_subfolder_trigger = restored_subfolder_data.get("trigger")

        assert original_subfolder_next_run == restored_subfolder_next_run, (
            "Subfolder job next run time preserved"
        )
        assert str(original_subfolder_trigger) == str(restored_subfolder_trigger), (
            "Subfolder job trigger preserved"
        )

        # Test 3: Schedule Change Detection
        # Overwrite the original file with updated schedule (every 1m → every 2m)
        self.create_file(vault, "AssistantMD/Workflows/quick_job.md", QUICK_JOB_UPDATED_WORKFLOW)
        await self.restart_system()

        new_events = self.events_since(checkpoint)
        checkpoint = self.event_checkpoint()

        updated_event = self.latest_event(
            new_events,
            name="job_synced",
            workflow_id="SystemTest/quick_job",
            action="replaced",
        )
        assert updated_event is not None, "Missing job_synced event after schedule update"
        updated_data = updated_event.get("data", {})
        updated_next_run = updated_data.get("next_run_time")
        updated_trigger = updated_data.get("trigger")

        assert str(original_trigger) != str(updated_trigger), (
            "Trigger changed after schedule update"
        )
        assert updated_next_run is not None, "Updated job should have next run time"

        # Test 4: Real-Time Scheduled Execution
        # Job runs every 2m (120s), so wait 150s to account for schedule + execution time
        checkpoint = self.event_checkpoint()
        execution_success = await self.trigger_job(vault, "quick_job")
        assert execution_success, "Job should execute when triggered"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="job_executed",
            expected={"job_id": "SystemTest__quick_job"},
        )

        today_file = f"results/{datetime.now().strftime('%Y-%m-%d')}.md"
        output_path = vault / today_file
        assert output_path.exists(), f"Expected {today_file} to be created"
        assert output_path.stat().st_size > 0, f"{today_file} is empty"

        # Test 5: Multiple Restart Cycle
        checkpoint = self.event_checkpoint()
        await self.restart_system()
        await self.restart_system()

        new_events = self.events_since(checkpoint)
        final_event = self.latest_event(
            new_events,
            name="job_synced",
            workflow_id="SystemTest/quick_job",
        )
        assert final_event is not None, "Missing job_synced event after restarts"
        final_next_run = final_event.get("data", {}).get("next_run_time")
        assert final_next_run is not None, "Job should survive multiple restarts"

        # Test 6: Malformed Workflow Resilience
        # Add a malformed workflow file with invalid schedule syntax
        self.create_file(vault, "AssistantMD/Workflows/malformed_schedule.md", MALFORMED_SCHEDULE_WORKFLOW)
        await self.restart_system()

        new_events = self.events_since(checkpoint)
        checkpoint = self.event_checkpoint()

        # Verify good workflows are still loaded and working
        self.assert_event_contains(
            new_events,
            name="workflow_loaded",
            expected={"workflow_id": "SystemTest/quick_job"},
        )
        self.assert_event_contains(
            new_events,
            name="workflow_loaded",
            expected={"workflow_id": "SystemTest/planning/quick_job_2"},
        )
        self.assert_event_contains(
            new_events,
            name="job_synced",
            expected={"job_id": "SystemTest__quick_job"},
        )
        self.assert_event_contains(
            new_events,
            name="job_synced",
            expected={"job_id": "SystemTest__planning__quick_job_2"},
        )

        # Verify the malformed workflow error was captured
        self.assert_event_contains(
            new_events,
            name="workflow_load_failed",
            expected={
                "vault": "SystemTest",
                "workflow_name": "malformed_schedule",
                "error_type": "ValueError",
            },
        )

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
@output file: results/{today}
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
@output file: results/{today}
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
@output file: results/{today}
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
@output file: test.md

This workflow has invalid schedule syntax (old format) and should fail to load without crashing the system.
"""
