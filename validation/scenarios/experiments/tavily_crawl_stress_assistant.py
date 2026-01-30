"""
Tavily Crawl Stress Test Workflow scenario - tests ambitious crawl parameters and error handling.

This scenario intentionally uses ambitious parameters to stress test the system
and observe timeout/error behavior without artificial validation timeouts.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# No more path isolation monkey patches needed! CoreServices handles clean dependency injection.

from validation.core.base_scenario import BaseScenario


class TavilyCrawlStressWorkflowScenario(BaseScenario):
    """Test Tavily crawl tool with ambitious parameters to observe timeout/error behavior."""
    
    async def test_scenario(self):
        """Execute stress test crawl workflow."""

        # === SETUP ===
        vault = self.create_vault("StressTestVault")

        # Create the stress test crawl workflow
        self.create_file(vault, "AssistantMD/Workflows/tavily-crawl-stress-workflow.md", TAVILY_CRAWL_STRESS_WORKFLOW)

        # === SYSTEM STARTUP VALIDATION ===
        await self.start_system()

        # Validate system startup
        assert "StressTestVault" in self.get_discovered_vaults(), "Vault not discovered"
        workflows = self.get_loaded_workflows()
        assert any(
            cfg.global_id == "StressTestVault/tavily-crawl-stress-workflow"
            for cfg in workflows
        ), "Workflow not loaded"
        jobs = self.get_scheduler_jobs()
        assert any(
            job.job_id == "StressTestVault__tavily-crawl-stress-workflow"
            for job in jobs
        ), "Scheduler job not created"

        # === STRESS TEST CRAWL EXECUTION ===
        self.set_date("2025-01-20")  # Monday

        # Trigger the ambitious crawl step (no timeout - observe natural behavior)
        self._log_timeline("🚀 Starting stress test crawl with ambitious parameters...")
        await self.trigger_job(vault, "tavily-crawl-stress-workflow")

        # === ASSERTIONS ===
        # Note: This may legitimately fail due to API timeouts - that's part of what we're testing
        assert len(self.get_job_executions(vault, "tavily-crawl-stress-workflow")) > 0, (
            "No executions recorded for StressTestVault/tavily-crawl-stress-workflow"
        )

        # Check that research file was created (if job succeeded)
        output_path = vault / "research" / "2025-01-20.md"
        assert output_path.exists(), "Expected research/2025-01-20.md to be created"
        assert output_path.stat().st_size > 0, "research/2025-01-20.md is empty"

        self._log_timeline("🏁 Stress test completed - review results for timeout/error patterns")

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

TAVILY_CRAWL_STRESS_WORKFLOW = """---
schedule: once: 2030-01-01 09:00
workflow_engine: step
enabled: true
description: Tavily crawl stress test with ambitious parameters - tests timeout behavior
---

## INSTRUCTIONS
You are a comprehensive research workflow that uses Tavily's crawl tool to deeply analyze websites. This is a stress test scenario to evaluate timeout and error handling behavior.

## DEEP_ANALYSIS_STEP
@model gemini-flash
@tools tavily_crawl
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output file: research/{today}

Perform a comprehensive crawl of the Tavily documentation website: https://docs.tavily.com/documentation/about

Use the crawl tool with ambitious parameters to stress test the system:
- Use deep exploration to find detailed documentation across multiple levels
- Use wide breadth to cover many different topic areas comprehensively
- Request thorough coverage of the documentation
- Use advanced extraction for complete, detailed content including tables and embedded elements

Your instructions for the crawl: "Find comprehensive documentation about Tavily including API reference, SDK guides, integration examples, endpoints documentation, and usage patterns. Extract detailed technical content from all relevant sections."

After crawling, provide a comprehensive analysis including:
- Detailed overview of the site structure and navigation
- Complete catalog of main sections and subsections discovered
- Technical depth analysis of API endpoints and SDK features found
- Key insights for developers using Tavily
- Comprehensive reference to available integrations and tools
- Assessment of documentation completeness and organization

This is intentionally ambitious to test system behavior under heavy load.
"""
