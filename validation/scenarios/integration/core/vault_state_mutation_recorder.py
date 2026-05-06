"""Integration scenario for vault-state task mutation recording."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class VaultStateMutationRecorderScenario(BaseScenario):
    """Validate file_ops_safe(write) records task-scoped vault mutations."""

    async def test_scenario(self):
        vault = self.create_vault("VaultStateMutationVault")
        self.create_file(vault, "AssistantMD/Authoring/write_probe.md", WRITE_PROBE_WORKFLOW)

        await self.start_system()

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "write_probe")
        events = self.events_since(checkpoint)

        self.soft_assert_equal(result.status, "completed", "Workflow write probe should complete")
        mutation_event = self.assert_event_contains(
            events,
            name="task_file_mutation_recorded",
            expected={
                "vault_name": vault.name,
                "path": "notes/created-by-workflow.md",
                "operation": "write",
                "before_exists": False,
                "after_exists": True,
            },
        )
        task_id = mutation_event["data"]["task_id"]
        vault_id = mutation_event["data"]["vault_id"]
        self.assert_event_contains(
            events,
            name="task_snapshot_created",
            expected={
                "task_id": task_id,
                "vault_id": vault_id,
                "vault_name": vault.name,
            },
        )
        self.assert_event_contains(
            events,
            name="task_file_snapshot_recorded",
            expected={
                "task_id": task_id,
                "vault_id": vault_id,
                "path": "notes/created-by-workflow.md",
                "before_exists": False,
            },
        )

        row = self._mutation_row(task_id)
        self.soft_assert(row is not None, "Mutation row should be persisted")
        if row is not None:
            self.soft_assert_equal(row["task_id"], task_id, "Mutation row task_id should match event")
            self.soft_assert_equal(row["vault_id"], vault_id, "Mutation row vault_id should match event")
            self.soft_assert_equal(row["path"], "notes/created-by-workflow.md", "Mutation path should match")
            self.soft_assert_equal(row["before_exists"], 0, "Mutation before_exists should be false")
            self.soft_assert_equal(row["after_exists"], 1, "Mutation after_exists should be true")
            self.soft_assert(row["after_hash"], "Mutation should capture after hash")
            self.soft_assert(row["event_sequence"] is not None, "Mutation should link vault event")
            self.soft_assert(row["expires_at"], "Mutation should have retention expiration")
            self.soft_assert_equal(
                row["snapshot_ref"],
                None,
                "Create-file snapshot should record absence without a file snapshot ref",
            )

        manifest = self._manifest_row(vault_id, "notes/created-by-workflow.md")
        self.soft_assert(manifest is not None, "Manifest should update immediately after write")
        if manifest is not None:
            self.soft_assert_equal(manifest["deleted_at"], None, "Created file should be active")
            self.soft_assert_equal(manifest["artifact_class"], "user_content", "Created note class")

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    def _mutation_row(self, task_id: str) -> dict | None:
        db_path = self._get_system_controller()._system_root / "vault_state.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT task_id, vault_id, vault_name, path, operation,
                       event_sequence, before_exists, before_hash,
                       after_exists, after_hash, snapshot_ref, expires_at
                FROM task_file_mutations
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def _manifest_row(self, vault_id: str, path: str) -> dict | None:
        db_path = self._get_system_controller()._system_root / "vault_state.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT vault_id, path, artifact_class, deleted_at
                FROM vault_files
                WHERE vault_id = ? AND path = ?
                """,
                (vault_id, path),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()


WRITE_PROBE_WORKFLOW = """---
run_type: workflow
enabled: false
description: Vault-state mutation recorder probe
---

## Run

```python
await file_ops_safe(
    operation="write",
    path="notes/created-by-workflow.md",
    content="Created by workflow\\n",
)
await finish(status="completed", reason="write-probe-done")
```
"""
