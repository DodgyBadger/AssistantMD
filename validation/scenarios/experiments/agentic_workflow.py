"""
Agentic Workflow scenario - tests autonomous task execution capabilities.

Tests how "agentic" the step workflow can be when given:
- No explicit @output-file directive
- Full file operation tools (safe + unsafe)
- A goal with minimal instruction on HOW to accomplish it

This explores the upper bounds of autonomous behavior within the current architecture.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class TestAgenticWorkflowScenario(BaseScenario):
    """Test autonomous task breakdown and execution with file operations."""

    async def test_scenario(self):
        """Execute agentic workflow with minimal instructions."""

        # === SETUP ===
        vault = self.create_vault("Research")

        # Create the agentic assistant
        self.create_file(vault, "assistants/agentic_assistant.md", AGENTIC_ASSISTANT)

        # === SYSTEM STARTUP ===
        await self.start_system()

        self.expect_vault_discovered("Research")
        self.expect_assistant_loaded("Research", "agentic_assistant")

        # === WORKFLOW EXECUTION ===
        self.set_date("2025-01-15")

        await self.trigger_job(vault, "agentic_assistant")

        # === ASSERTIONS ===
        self.expect_scheduled_execution_success(vault, "agentic_assistant")

        # The assistant should create files autonomously
        # We intentionally don't specify WHAT files to see what it does

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === ASSISTANT TEMPLATES ===

AGENTIC_ASSISTANT = """---
schedule: cron: 0 9 * * *
workflow: step
enabled: true
description: Agentic assistant that autonomously manages task execution
---

## INSTRUCTIONS

You are an autonomous task execution assistant with full control over file creation and management. Break down objectives into actionable steps, track your progress, and execute tasks systematically.

When given a goal:
1. First, create a task list file that breaks down the goal into specific steps
2. Execute each step, creating files as needed
3. Update your task list file to mark steps as completed

## STEP1
@tools file_ops_safe,file_ops_unsafe, code_execution
@model sonnet

**Goal**: Analyze a simple dataset - create sample data, calculate statistics, and generate a summary report.

Break this down into steps. Write your task plan to a file, execute each analytical step (you can create sample data in files), then compile results into a final report.
"""
