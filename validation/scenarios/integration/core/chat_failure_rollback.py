"""Integration scenario for automatic rollback after chat execution failure."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.chat.executor import PreparedChatExecution, execute_chat_prompt
from core.runtime.execution_tasks import chat_session_scope
from core.runtime.state import get_runtime_context
from core.vault_state.file_mutations import write_vault_file
from validation.core.base_scenario import BaseScenario


class _FailingAgent:
    """Fake agent that mutates a file and then fails."""

    def __init__(self, vault_path: Path):
        self._vault_path = vault_path

    async def run(self, *args, **kwargs):
        write_vault_file(
            vault_path=self._vault_path,
            path="notes/failed-chat-write.md",
            content="created before chat failure\n",
        )
        raise RuntimeError("forced chat failure after mutation")


class ChatFailureRollbackScenario(BaseScenario):
    """Validate failed chat tasks rollback recorded vault file mutations."""

    async def test_scenario(self):
        vault = self.create_vault("ChatFailureRollbackVault")

        await self.start_system()

        import core.chat.executor as chat_executor

        async def _prepared_failing_chat(*args, **kwargs):
            return PreparedChatExecution(
                agent=_FailingAgent(vault),
                message_history=None,
                prompt_for_history="Fail after mutating a file.",
                user_prompt="Fail after mutating a file.",
                attached_image_count=0,
                model="test",
                tools=[],
            )

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        chat_executor._prepare_chat_execution = _prepared_failing_chat
        session_id = "chat_failure_rollback_session"
        try:
            checkpoint = self.event_checkpoint()
            caught = None
            try:
                await execute_chat_prompt(
                    vault_name=vault.name,
                    vault_path=str(vault),
                    prompt="Fail after mutating a file.",
                    image_paths=[],
                    image_uploads=[],
                    session_id=session_id,
                    tools=[],
                    model="test",
                    context_template=None,
                )
            except RuntimeError as exc:
                caught = exc
            events = self.events_since(checkpoint)

            self.soft_assert(caught is not None, "Forced chat failure should propagate")
            failed_event = self.assert_event_contains(
                events,
                name="execution_task_failed",
                expected={
                    "kind": "chat",
                    "scope": chat_session_scope(session_id),
                    "status": "failed",
                },
            )
            task_id = failed_event["data"]["task_id"]
            self.assert_event_contains(
                events,
                name="task_rollback_completed",
                expected={
                    "task_id": task_id,
                    "terminal_status": "failed",
                },
            )
            self.soft_assert(
                not (Path(vault) / "notes/failed-chat-write.md").exists(),
                "Failed chat task should rollback files created before failure",
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            await self.stop_system()
            self.teardown_scenario()
            self.assert_no_failures()
