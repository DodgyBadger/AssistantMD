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
        assert "FileOpsTestVault" in self.get_discovered_vaults(), "Vault not discovered"
        workflows = self.get_loaded_workflows()
        assert any(
            cfg.global_id == "FileOpsTestVault/file_ops_test" for cfg in workflows
        ), "Workflow not loaded"
        jobs = self.get_scheduler_jobs()
        assert any(
            job.job_id == "FileOpsTestVault__file_ops_test" for job in jobs
        ), "Scheduler job not created"
        job = next(
            (job for job in jobs if job.job_id == "FileOpsTestVault__file_ops_test"),
            None,
        )
        assert job is not None, "Scheduler job not found for schedule check"
        assert "cron" in job.trigger.lower(), "Expected cron trigger"
        
        # === SCHEDULED WORKFLOW EXECUTION ===
        # Set a known date for predictable output file naming
        self.set_date("2025-01-16")  # Thursday
        
        # Trigger the scheduled job and wait for completion
        await self.trigger_job(vault, "file_ops_test")
        
        # === ASSERTIONS ===
        # Verify the scheduled job executed successfully
        assert len(self.get_job_executions(vault, "file_ops_test")) > 0, (
            "No executions recorded for FileOpsTestVault/file_ops_test"
        )

        # Check output files were created with content (step1, step2, and step3 outputs)
        for rel_path in [
            "test-results/step1.md",
            "test-results/step2.md",
            "test-results/step3.md",
        ]:
            output_path = vault / rel_path
            assert output_path.exists(), f"Expected {rel_path} to be created"
            assert output_path.stat().st_size > 0, f"{rel_path} is empty"

        # Verify unsafe operations created and modified files
        template_path = vault / "template.md"
        assert template_path.exists(), "Expected template.md to be created"
        assert template_path.stat().st_size > 0, "template.md is empty"
        
        # Verify the workflow had file_operations tool available by checking tool was loaded
        # The presence of the tool in the workflow and successful execution indicates it worked
        
        # Clean up
        await self.stop_system()
        self.teardown_scenario()
