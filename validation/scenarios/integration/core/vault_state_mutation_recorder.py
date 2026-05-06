"""Integration scenario for vault-state task mutation recording."""

import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario
from core.chat.schema import ensure_chat_sessions_schema


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
            self.soft_assert_equal(row["task_kind"], "workflow", "Mutation row should persist task kind")
            self.soft_assert_equal(row["task_source"], "api", "Mutation row should persist task source")
            self.soft_assert_equal(row["task_label"], f"{vault.name}/write_probe", "Mutation row should persist task label")
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

        response = self.call_api(
            f"/api/vaults/{vault.name}/task-mutations",
            params={"limit": 5},
        )
        self.soft_assert_equal(response.status_code, 200, "Task mutation activity API should respond")
        payload = response.json()
        groups = payload.get("groups", [])
        api_group = next((group for group in groups if group.get("task_id") == task_id), None)
        self.soft_assert(api_group is not None, "Task mutation activity API should include workflow task")
        if api_group is not None:
            self.soft_assert_equal(api_group.get("activity_id"), task_id, "Workflow activity id should be task id")
            self.soft_assert_equal(api_group.get("activity_kind"), "workflow", "Workflow activity kind should match")
            self.soft_assert_equal(api_group.get("task_kind"), "workflow", "API should expose task kind")
            self.soft_assert_equal(api_group.get("task_source"), "api", "API should expose task source")
            self.soft_assert_equal(
                api_group.get("task_label"),
                f"{vault.name}/write_probe",
                "API should expose task label",
            )
            self.soft_assert_equal(api_group.get("mutation_count"), 1, "API should group one mutation")
            mutations = api_group.get("mutations", [])
            self.soft_assert_equal(len(mutations), 1, "API group should include mutation row")
            if mutations:
                self.soft_assert_equal(
                    mutations[0].get("path"),
                    "notes/created-by-workflow.md",
                    "API mutation path should match",
                )
                self.soft_assert_equal(
                    mutations[0].get("operation"),
                    "write",
                    "API mutation operation should match",
                )
                self.soft_assert(
                    mutations[0].get("event_sequence") is not None,
                    "API mutation should include event sequence",
                )

        self._insert_chat_session(vault_name=vault.name)
        self._insert_chat_mutation_rows(vault_id=vault_id, vault_name=vault.name)
        chat_response = self.call_api(
            f"/api/vaults/{vault.name}/task-mutations",
            params={"limit": 5},
        )
        self.soft_assert_equal(chat_response.status_code, 200, "Chat activity API should respond")
        chat_groups = chat_response.json().get("groups", [])
        chat_group = next(
            (
                group
                for group in chat_groups
                if group.get("activity_id") == "chat_session:validation-session"
            ),
            None,
        )
        self.soft_assert(chat_group is not None, "Direct chat mutations should group by chat session")
        if chat_group is not None:
            self.soft_assert_equal(chat_group.get("activity_kind"), "chat", "Chat activity kind should match")
            self.soft_assert_equal(
                chat_group.get("chat_session_id"),
                "validation-session",
                "Chat group should expose session id",
            )
            self.soft_assert_equal(
                chat_group.get("chat_session_title"),
                "Validation Chat Title",
                "Chat group should expose session title",
            )
            self.soft_assert_equal(chat_group.get("mutation_count"), 2, "Chat group should include both turns")
            chat_task_ids = {
                mutation.get("task_id")
                for mutation in chat_group.get("mutations", [])
            }
            self.soft_assert_equal(
                chat_task_ids,
                {"chat-task-1", "chat-task-2"},
                "Chat group should retain per-turn task ids",
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
                SELECT task_id, task_kind, task_source, task_scope, task_label,
                       vault_id, vault_name, path, operation,
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

    def _insert_chat_session(self, *, vault_name: str) -> None:
        system_root = self._get_system_controller()._system_root
        ensure_chat_sessions_schema(str(system_root))
        db_path = system_root / "chat_sessions.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO chat_sessions (
                    session_id, vault_name, created_at, last_activity_at, title, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "validation-session",
                    vault_name,
                    "2026-05-06 17:00:00",
                    "2026-05-06 17:05:00",
                    "Validation Chat Title",
                    None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _insert_chat_mutation_rows(self, *, vault_id: str, vault_name: str) -> None:
        db_path = self._get_system_controller()._system_root / "vault_state.db"
        now = datetime.now(UTC)
        rows = [
            (
                "chat-task-1",
                "chat",
                "api",
                "chat_session:validation-session",
                "chat:validation-session",
                vault_id,
                vault_name,
                "notes/chat-one.md",
                "write",
                None,
                0,
                None,
                1,
                "chat-after-hash-1",
                None,
                now.isoformat(),
                (now + timedelta(days=7)).isoformat(),
            ),
            (
                "chat-task-2",
                "chat",
                "api",
                "chat_session:validation-session",
                "chat:validation-session",
                vault_id,
                vault_name,
                "notes/chat-two.md",
                "write",
                None,
                0,
                None,
                1,
                "chat-after-hash-2",
                None,
                (now + timedelta(seconds=1)).isoformat(),
                (now + timedelta(days=7)).isoformat(),
            ),
        ]
        conn = sqlite3.connect(db_path)
        try:
            conn.executemany(
                """
                INSERT INTO task_file_mutations (
                    task_id, task_kind, task_source, task_scope, task_label,
                    vault_id, vault_name, path, operation, event_sequence,
                    before_exists, before_hash, after_exists, after_hash,
                    snapshot_ref, created_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
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
