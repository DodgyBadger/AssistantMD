"""Integration scenario for workflow failure vault-state rollback."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.vault_state.rollback import rollback_task_file_mutations
from validation.core.base_scenario import BaseScenario


class VaultStateRollbackScenario(BaseScenario):
    """Validate failed workflow tasks rollback recorded vault file mutations."""

    async def test_scenario(self):
        vault = self.create_vault("VaultStateRollbackVault")
        self.create_file(vault, "notes/preexisting-append.md", "Original append\n")
        self.create_file(vault, "notes/preexisting-delete.md", "Original delete\n")
        self.create_file(vault, "notes/move-source.md", "Original move source\n")
        self.create_file(vault, "AssistantMD/Authoring/failing_probe.md", FAILING_PROBE_WORKFLOW)

        await self.start_system()

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "failing_probe", expect_failure=True)
        events = self.events_since(checkpoint)

        self.soft_assert_equal(result.status, "failed", "Workflow failure should be reported")
        failed_event = self.assert_event_contains(
            events,
            name="workflow_task_failed",
            expected={
                "workflow_id": f"{vault.name}/failing_probe",
                "status": "failed",
            },
        )
        task_id = failed_event["data"]["task_id"]
        self.assert_event_contains(
            events,
            name="task_rollback_started",
            expected={
                "task_id": task_id,
                "terminal_status": "failed",
            },
        )
        self.assert_event_contains(
            events,
            name="task_rollback_completed",
            expected={
                "task_id": task_id,
                "terminal_status": "failed",
            },
        )

        self.soft_assert(
            not (Path(vault) / "notes/created-before-failure.md").exists(),
            "Rollback should delete files created by the failed workflow",
        )
        self.soft_assert_equal(
            (Path(vault) / "notes/preexisting-append.md").read_text(encoding="utf-8"),
            "Original append\n",
            "Rollback should restore appended file content",
        )
        self.soft_assert_equal(
            (Path(vault) / "notes/preexisting-delete.md").read_text(encoding="utf-8"),
            "Original delete\n",
            "Rollback should restore deleted file content",
        )
        self.soft_assert_equal(
            (Path(vault) / "notes/move-source.md").read_text(encoding="utf-8"),
            "Original move source\n",
            "Rollback should restore moved source content",
        )
        self.soft_assert(
            not (Path(vault) / "notes/move-destination.md").exists(),
            "Rollback should remove moved destination file",
        )

        snapshot_status = self._snapshot_status(task_id)
        self.soft_assert_equal(snapshot_status, "rolled_back", "Task snapshot should be marked rolled back")
        retry_result = rollback_task_file_mutations(
            task_id=task_id,
            terminal_status="failed",
            reason="validation retry",
        )
        self.soft_assert(retry_result.skipped, "Second rollback should be skipped")
        self.soft_assert_equal(
            retry_result.reason,
            "already_rolled_back",
            "Second rollback should report already rolled back",
        )
        self.soft_assert_equal(
            retry_result.mutation_rows_seen,
            len(self._mutation_rows(task_id)),
            "Second rollback should still report retained mutation rows",
        )
        self.soft_assert(
            not (Path(vault) / "notes/created-before-failure.md").exists(),
            "Second rollback should leave created file deleted",
        )
        self.soft_assert_equal(
            (Path(vault) / "notes/preexisting-append.md").read_text(encoding="utf-8"),
            "Original append\n",
            "Second rollback should not change restored append content",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    def _snapshot_status(self, task_id: str) -> str | None:
        db_path = self._get_system_controller()._system_root / "vault_state.db"
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT status FROM snapshot_sets WHERE task_id = ? AND purpose = 'rollback'",
                (task_id,),
            ).fetchone()
            return row[0] if row is not None else None
        finally:
            conn.close()

    def _mutation_rows(self, task_id: str) -> list[tuple]:
        db_path = self._get_system_controller()._system_root / "vault_state.db"
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                "SELECT id FROM task_file_mutations WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        finally:
            conn.close()


FAILING_PROBE_WORKFLOW = """---
run_type: workflow
enabled: false
description: Vault-state rollback failure probe
---

## Run

```python
await file_ops_safe(
    operation="write",
    path="notes/created-before-failure.md",
    content="created then rolled back\\n",
)
await file_ops_safe(
    operation="append",
    path="notes/preexisting-append.md",
    content="mutated append\\n",
)
await file_ops_unsafe(
    operation="delete",
    path="notes/preexisting-delete.md",
    confirm_path="notes/preexisting-delete.md",
)
await file_ops_safe(
    operation="move",
    path="notes/move-source.md",
    destination="notes/move-destination.md",
)
raise RuntimeError("rollback probe failure")
```
"""
