"""
Integration scenario covering hybrid {pending} handling.

Ensures in-place edits made during a run don't re-queue files, while later edits
do re-queue.
"""

import os
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.directives.file_state import WorkflowFileStateManager
from core.directives.pattern_utilities import PatternUtilities
from validation.core.base_scenario import BaseScenario


class PendingHybridScenario(BaseScenario):
    """Validate hybrid pending state tracking."""

    async def test_scenario(self):
        vault = self.create_vault("PendingHybridVault")
        tasks_dir = vault / "tasks"
        os.makedirs(tasks_dir, exist_ok=True)

        # Seed two files; both should be processed on the first run
        task_files = [
            tasks_dir / "task1.md",
            tasks_dir / "task2.md",
        ]
        for idx, path in enumerate(task_files, start=1):
            path.write_text(f"Task {idx}\n", encoding="utf-8")

        # Keep original mtimes so we can simulate "edit before processed_at"
        original_mtimes = {str(p): p.stat().st_mtime for p in task_files}

        self.create_file(
            vault,
            "AssistantMD/Workflows/pending_hybrid.md",
            PENDING_HYBRID_WORKFLOW,
        )

        await self.start_system()

        self.expect_vault_discovered("PendingHybridVault")
        self.expect_workflow_loaded("PendingHybridVault", "pending_hybrid")

        pattern = "tasks/{pending:5}"
        state_manager = WorkflowFileStateManager(
            vault_name="PendingHybridVault",
            workflow_id="PendingHybridVault/pending_hybrid",
        )

        # Run 1: process both files
        result = await self.run_workflow(vault, "pending_hybrid")
        self.expect_equals(result.status, "completed", "Initial run should succeed")
        self.expect_pending_count(state_manager, tasks_dir, pattern, expected=0)

        # Simulate workflow self-edit: change a file but keep mtime before processed_at
        task1 = task_files[0]
        task1.write_text(task1.read_text(encoding="utf-8") + "self-edit\n", encoding="utf-8")
        os.utime(task1, times=(original_mtimes[str(task1)], original_mtimes[str(task1)]))

        result = await self.run_workflow(vault, "pending_hybrid")
        self.expect_equals(
            result.status,
            "completed",
            "Second run should succeed without re-queuing self-edited file",
        )
        self.expect_pending_count(state_manager, tasks_dir, pattern, expected=0)

        # Simulate user edit after processing; should re-queue
        task1.write_text(task1.read_text(encoding="utf-8") + "user-edit\n", encoding="utf-8")
        os.utime(task1, None)  # bump mtime to now

        pending_before = self.get_pending(state_manager, tasks_dir, pattern)
        self.expect_equals(len(pending_before), 1, "User edit should re-queue file")

        result = await self.run_workflow(vault, "pending_hybrid")
        self.expect_equals(result.status, "completed", "Third run should succeed")
        self.expect_pending_count(state_manager, tasks_dir, pattern, expected=0)

        await self.stop_system()
        self.teardown_scenario()

    def get_pending(
        self,
        state_manager: WorkflowFileStateManager,
        tasks_dir: Path,
        pattern: str,
    ) -> List[str]:
        files = PatternUtilities.get_directory_files(str(tasks_dir))
        return state_manager.get_pending_files(files, pattern)

    def expect_pending_count(
        self,
        state_manager: WorkflowFileStateManager,
        tasks_dir: Path,
        pattern: str,
        expected: int,
    ):
        pending = self.get_pending(state_manager, tasks_dir, pattern)
        self.expect_equals(len(pending), expected, f"Expected {expected} pending files")


# === WORKFLOW TEMPLATE ===

PENDING_HYBRID_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Pending hybrid validation
---

## STEP1
@model test
@input-file tasks/{pending:5}
@output-file logs/run-{today}

Summarize the pending files encountered. Do not modify file contents.
"""
