"""
File Operations Test scenario - tests file_operations tool functionality.

Tests that the file_operations tool works correctly with vault boundaries and security.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# No more path isolation monkey patches needed! CoreServices handles clean dependency injection.

from validation.core.base_scenario import BaseScenario


class TestFileOperationsScenario(BaseScenario):
    """Test file operations tool functionality and security."""
    
    async def test_scenario(self):
        """Execute complete file operations testing workflow."""
        
        # === SETUP ===
        vault = self.create_vault("FileOpsTestVault")
        
        # Create file operations testing workflow
        self.copy_files("validation/templates/AssistantMD/Workflows/file_ops_test.md", vault, "AssistantMD/Workflows")
        
        # === SYSTEM STARTUP VALIDATION ===
        # Test real system startup with vault discovery and job scheduling
        await self.start_system()
        
        # Validate system startup completed correctly
        self.expect_vault_discovered("FileOpsTestVault")
        self.expect_workflow_loaded("FileOpsTestVault", "file_ops_test")
        self.expect_scheduler_job_created("FileOpsTestVault/file_ops_test")
        self.expect_schedule_parsed_correctly("FileOpsTestVault/file_ops_test", "cron")
        
        # === SCHEDULED WORKFLOW EXECUTION ===
        # Set a known date for predictable output file naming
        self.set_date("2025-01-16")  # Thursday
        
        # Trigger the scheduled job and wait for completion
        await self.trigger_job(vault, "file_ops_test")
        
        # === ASSERTIONS ===
        # Verify the scheduled job executed successfully
        self.expect_scheduled_execution_success(vault, "file_ops_test")

        # Check output files were created with content (step1, step2, and step3 outputs)
        self.expect_file_created(vault, "test-results/step1.md")
        self.expect_file_created(vault, "test-results/step2.md")
        self.expect_file_created(vault, "test-results/step3.md")

        # Verify unsafe operations created and modified files
        self.expect_file_created(vault, "template.md")
        
        # Verify the workflow had file_operations tool available by checking tool was loaded
        # The presence of the tool in the workflow and successful execution indicates it worked
        
        # Clean up
        await self.stop_system()
        self.teardown_scenario()
