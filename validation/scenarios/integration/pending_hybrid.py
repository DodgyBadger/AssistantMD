"""
Integration scenario covering hybrid {pending} handling.

Ensures in-place edits made during a run don't re-queue files, while later edits
do re-queue.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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

        checkpoint = self.event_checkpoint()
        await self.start_system()

        assert "PendingHybridVault" in self.get_discovered_vaults(), "Vault not discovered"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "PendingHybridVault/pending_hybrid"},
        )

        pattern = "tasks/{pending:5}"
        workflow_id = "PendingHybridVault/pending_hybrid"

        # Run 1: process both files
        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "pending_hybrid")
        assert result.status == "completed", "Initial run should succeed"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={
                "workflow_id": workflow_id,
                "pattern": pattern,
                "pending_count": 2,
            },
        )

        # Simulate workflow self-edit: change a file but keep mtime before processed_at
        task1 = task_files[0]
        task1.write_text(task1.read_text(encoding="utf-8") + "self-edit\n", encoding="utf-8")
        os.utime(task1, times=(original_mtimes[str(task1)], original_mtimes[str(task1)]))

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "pending_hybrid")
        assert result.status == "completed", (
            "Second run should succeed without re-queuing self-edited file"
        )
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={
                "workflow_id": workflow_id,
                "pattern": pattern,
                "pending_count": 0,
            },
        )

        # Simulate user edit after processing; should re-queue
        task1.write_text(task1.read_text(encoding="utf-8") + "user-edit\n", encoding="utf-8")
        os.utime(task1, None)  # bump mtime to now

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "pending_hybrid")
        assert result.status == "completed", "Third run should succeed"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={
                "workflow_id": workflow_id,
                "pattern": pattern,
                "pending_count": 1,
                "pending_paths": ["tasks/task1.md"],
            },
        )

        await self.stop_system()
        self.teardown_scenario()

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
