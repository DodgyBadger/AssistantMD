"""Validate single-principal ownership and execution-authority propagation."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat.chat_store import ChatStore
from core.identity import (
    LOCAL_USER_AUTHORITY,
    LOCAL_USER_PRINCIPAL_ID,
    SYSTEM_AUTHORITY,
    get_current_execution_authority,
    require_current_execution_authority,
    use_execution_authority,
)
from core.runtime.execution_tasks import ExecutionTaskKind, ExecutionTaskSource
from core.runtime.state import get_runtime_context
from core.runtime.task_runner import ExecutionTaskSpec
from core.runtime.workflow_governor import _authority_for_workflow_source
from core.system_migrations import run_system_migrations
from validation.core.base_scenario import BaseScenario


class PrincipalExecutionAuthorityScenario(BaseScenario):
    """Validate legacy ownership migration and task-local authority."""

    async def test_scenario(self) -> None:
        system_root = self.artifacts_dir / "system"
        system_root.mkdir(parents=True, exist_ok=True)
        chat_db = system_root / "chat_sessions.db"
        self._create_legacy_chat_database(chat_db)

        ChatStore(str(system_root))
        run_system_migrations(system_root, backup=False)
        store = ChatStore(str(system_root))
        legacy = store.get_session_by_id("legacy-session")
        self.soft_assert_equal(
            legacy.owner_principal_id if legacy else None,
            LOCAL_USER_PRINCIPAL_ID,
            "Legacy sessions should migrate to the local user",
        )

        created = store.ensure_session(
            "owned-session",
            "PrincipalVault",
            owner_principal_id=LOCAL_USER_PRINCIPAL_ID,
        )
        self.soft_assert_equal(
            created.owner_principal_id,
            LOCAL_USER_PRINCIPAL_ID,
            "New sessions should persist their owner",
        )
        mismatch_rejected = False
        try:
            store.ensure_session(
                "owned-session",
                "PrincipalVault",
                owner_principal_id="different-user",
            )
        except ValueError:
            mismatch_rejected = True
        self.soft_assert(
            mismatch_rejected,
            "Existing session ownership should be immutable",
        )
        unchanged = store.get_session_by_id("owned-session")
        self.soft_assert_equal(
            unchanged.owner_principal_id if unchanged else None,
            LOCAL_USER_PRINCIPAL_ID,
            "A rejected owner rebind should not modify the stored owner",
        )

        await self.start_system()
        runtime = get_runtime_context()
        lifecycle_checkpoint = self.event_checkpoint()
        observed: list[str | None] = []
        task = await runtime.task_runner.start_background(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.CHAT,
                scope="principal:interactive",
                source=ExecutionTaskSource.API,
                label="principal-interactive",
                authority=LOCAL_USER_AUTHORITY,
            ),
            lambda _task: _capture_authority(observed),
        )
        terminal = await self._wait_for_task_terminal(task.task_id)
        self.soft_assert_equal(
            terminal.principal_id if terminal else None,
            LOCAL_USER_PRINCIPAL_ID,
            "Task snapshots should retain the captured principal",
        )
        self.soft_assert_equal(
            observed,
            [LOCAL_USER_PRINCIPAL_ID],
            "Detached workers should observe the captured authority",
        )
        lifecycle_events = [
            event
            for event in self.events_since(lifecycle_checkpoint)
            if event.get("data", {}).get("task_id") == task.task_id
        ]
        self.soft_assert_equal(
            [event.get("name") for event in lifecycle_events],
            [
                "execution_task_created",
                "execution_task_started",
                "execution_task_completed",
            ],
            "Task lifecycle should emit created, started, and terminal events",
        )
        self.soft_assert(
            all(
                event.get("data", {}).get("principal_id") == LOCAL_USER_PRINCIPAL_ID
                for event in lifecycle_events
            ),
            "Task lifecycle events should retain the captured principal",
        )

        system_observed: list[str | None] = []
        await runtime.task_runner.run_inline(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.HISTORY_COMPACTION,
                scope="principal:system",
                source=ExecutionTaskSource.SYSTEM,
                label="principal-system",
                authority=SYSTEM_AUTHORITY,
            ),
            lambda _task: _capture_authority(system_observed),
        )
        self.soft_assert_equal(
            system_observed,
            [SYSTEM_AUTHORITY.principal_id],
            "System work should observe system authority",
        )
        self.soft_assert_equal(
            get_current_execution_authority(),
            None,
            "Execution authority should reset after task completion",
        )

        nested_observed: list[str | None] = []

        async def _run_nested(_task) -> None:
            inherited = require_current_execution_authority()
            await runtime.task_runner.run_inline(
                ExecutionTaskSpec(
                    kind=ExecutionTaskKind.WORKFLOW,
                    scope="principal:nested",
                    source=ExecutionTaskSource.TOOL,
                    label="principal-nested",
                    authority=inherited,
                ),
                lambda _nested_task: _capture_authority(nested_observed),
            )

        await runtime.task_runner.run_inline(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.CHAT,
                scope="principal:parent",
                source=ExecutionTaskSource.API,
                label="principal-parent",
                authority=LOCAL_USER_AUTHORITY,
            ),
            _run_nested,
        )
        self.soft_assert_equal(
            nested_observed,
            [LOCAL_USER_PRINCIPAL_ID],
            "Nested work should inherit the active authority explicitly",
        )

        thread_observed = await runtime.task_runner.run_inline(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.INGESTION,
                scope="principal:thread",
                source=ExecutionTaskSource.SCHEDULER,
                label="principal-thread",
                authority=SYSTEM_AUTHORITY,
            ),
            lambda _task: asyncio.to_thread(_current_principal_id),
        )
        self.soft_assert_equal(
            thread_observed,
            SYSTEM_AUTHORITY.principal_id,
            "Threaded workers should retain captured system authority",
        )
        self.soft_assert_equal(
            get_current_execution_authority(),
            None,
            "Nested and threaded execution should reset authority context",
        )
        self.soft_assert_equal(
            _authority_for_workflow_source(ExecutionTaskSource.API).principal_id,
            LOCAL_USER_PRINCIPAL_ID,
            "API workflows should default to the interactive principal",
        )
        self.soft_assert_equal(
            _authority_for_workflow_source(ExecutionTaskSource.SCHEDULER).principal_id,
            SYSTEM_AUTHORITY.principal_id,
            "Scheduled workflows should default to system authority",
        )
        with use_execution_authority(LOCAL_USER_AUTHORITY):
            inherited_workflow = _authority_for_workflow_source(
                ExecutionTaskSource.TOOL
            )
        self.soft_assert_equal(
            inherited_workflow.principal_id,
            LOCAL_USER_PRINCIPAL_ID,
            "Tool workflows should inherit current authority",
        )
        self.assert_no_failures()
        self.teardown_scenario()

    @staticmethod
    async def _wait_for_task_terminal(task_id: str):
        runtime = get_runtime_context()
        for _ in range(100):
            task = await runtime.task_coordinator.get_task(task_id)
            if task is not None and task.is_terminal:
                return task
            await asyncio.sleep(0.02)
        return None

    @staticmethod
    def _create_legacy_chat_database(path: Path) -> None:
        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE chat_sessions (
                    session_id TEXT NOT NULL,
                    vault_name TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    title TEXT,
                    metadata_json TEXT,
                    PRIMARY KEY (session_id, vault_name)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (session_id, vault_name)
                VALUES ('legacy-session', 'PrincipalVault')
                """
            )


async def _capture_authority(observed: list[str | None]) -> None:
    authority = get_current_execution_authority()
    observed.append(authority.principal_id if authority else None)


def _current_principal_id() -> str | None:
    authority = get_current_execution_authority()
    return authority.principal_id if authority else None
