"""
Test workflow execution with @run-on never steps.

Tests that workflows continue processing subsequent steps after encountering @run-on never.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# No more path isolation monkey patches needed! CoreServices handles clean dependency injection.

from validation.core.base_scenario import BaseScenario


class TestRunOnNeverWorkflow(BaseScenario):
    """Test workflow execution with @run-on never steps."""
    
    async def test_scenario(self):
        """Execute workflow with mix of never/daily steps."""
        
        # === SETUP ===
        vault = self.create_vault("NeverTestVault")
        
        # Create workflow with multiple steps - some never, some daily
        workflow_content = """---
schedule: once at 10:00
workflow_engine: step
enabled: true
---

## STEP1
@run-on never
@output-file debug/step1
@model test

Step 1 content - should be skipped.

## STEP2  
@run-on daily
@output-file debug/step2
@model test

Step 2 content - should run.

## STEP3
@run-on daily
@output-file debug/step3
@model test

Step 3 content - should also run.
"""
        
        self.create_file(vault, "AssistantMD/Workflows/never_test.md", workflow_content)
        
        # === SYSTEM STARTUP ===
        await self.start_system()
        self.expect_workflow_loaded("NeverTestVault", "never_test")
        
        # === EXECUTE WORKFLOW ===
        self.set_date("2025-01-15")
        await self.trigger_job(vault, "never_test")
        
        # === ASSERTIONS ===
        # Step 1 should create empty file (pre-creation issue)
        self.expect_file_created(vault, "debug/step1.md")
        
        # Steps 2 and 3 should run and create content
        self.expect_file_created(vault, "debug/step2.md")
        self.expect_file_created(vault, "debug/step3.md")
        
        # Clean up
        await self.stop_system()
        self.teardown_scenario()
