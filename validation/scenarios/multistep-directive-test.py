"""
Daily Task Workflow scenario - tests multi-step execution with input files.

Tests complex workflow with multiple steps, input file dependencies, and time-based execution.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# No more path isolation monkey patches needed! CoreServices handles clean dependency injection.

from validation.core.base_scenario import BaseScenario


class DailyTaskWorkflowScenario(BaseScenario):
    """Test daily task workflow with multi-step execution and input files."""
    
    async def test_scenario(self):
        """Execute complete daily task workflow across a full week."""
        
        # === SETUP ===
        vault = self.create_vault("TaskVault")
        
        # Copy the daily-task workflow and task-list from validation templates
        self.copy_files("validation/templates/AssistantMD/Workflows/daily-task-workflow.md", vault, "AssistantMD/Workflows")
        self.copy_files("validation/templates/files/task-list.md", vault)
        
        # === SYSTEM STARTUP VALIDATION ===
        await self.start_system()
        
        # Validate system startup
        self.expect_vault_discovered("TaskVault")
        self.expect_workflow_loaded("TaskVault", "daily-task-workflow")
        self.expect_scheduler_job_created("TaskVault/daily-task-workflow")
        
        # === DAILY TASK EXECUTION (Monday through Thursday) ===
        weekdays = [
            ("2025-01-13", "Monday"),
            ("2025-01-14", "Tuesday"),
            ("2025-01-15", "Wednesday"),
            ("2025-01-16", "Thursday")
        ]

        for date, day_name in weekdays:
            self.set_date(date)

            # Trigger the daily task step
            await self.trigger_job(vault, "daily-task-workflow")

            # Verify daily execution succeeded
            self.expect_scheduled_execution_success(vault, "daily-task-workflow")

        # === VERIFY WRITE-MODE NEW CREATED NUMBERED FILES ===
        # The DAILY_TASKS step uses @write-mode new, so each run should create a numbered file
        # We ran 4 times on the same week (Mon-Thu), so we expect 4 numbered files:
        self.expect_file_created(vault, "daily-tasks-2025-01-13_000.md")
        self.expect_file_created(vault, "daily-tasks-2025-01-13_001.md")
        self.expect_file_created(vault, "daily-tasks-2025-01-13_002.md")
        self.expect_file_created(vault, "daily-tasks-2025-01-13_003.md")

        # === WEEKLY SUMMARY EXECUTION (Friday) ===
        # Test WEEKLY_SUMMARY step on Friday
        self.set_date("2025-01-17")  # Friday

        # Trigger the weekly summary step
        await self.trigger_job(vault, "daily-task-workflow")

        # === ASSERTIONS FOR WEEKLY SUMMARY ===
        self.expect_scheduled_execution_success(vault, "daily-task-workflow")

        self.expect_file_created(vault, "summary-2025-01-13.md")
        
        # Clean up
        await self.stop_system()
        self.teardown_scenario()
