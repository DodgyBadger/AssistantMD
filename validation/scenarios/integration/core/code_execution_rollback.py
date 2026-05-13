"""Integration scenario for code_execution mutations under parent task rollback."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from core.chat.executor import PreparedChatExecution, execute_chat_prompt
from core.runtime.execution_tasks import chat_session_scope
from core.tools.code_execution import CodeExecution
from validation.core.base_scenario import BaseScenario


class _CodeExecutionFailingAgent:
    """Fake chat agent that mutates via code_execution and then fails."""

    def __init__(self, vault_path: Path):
        self._vault_path = vault_path

    async def run(self, *args, **kwargs):
        deps = kwargs["deps"]
        tool = CodeExecution.get_tool(str(self._vault_path))
        ctx = RunContext(
            deps=deps,
            model=TestModel(),
            usage=RunUsage(),
        )
        result = await tool.function(
            ctx,
            code=(
                'await file_ops_safe(\n'
                '    operation="write",\n'
                '    path="notes/code-execution-write.md",\n'
                '    content="created inside code_execution\\n",\n'
                ')\n'
                '"CODE_EXECUTION_WRITE_OK"\n'
            ),
        )
        if "CODE_EXECUTION_WRITE_OK" not in result:
            raise RuntimeError(f"code_execution mutation failed before parent failure: {result}")
        raise RuntimeError("forced parent chat failure after code_execution mutation")


class CodeExecutionRollbackScenario(BaseScenario):
    """Validate code_execution file mutations rollback with the parent chat task."""

    async def test_scenario(self):
        vault = self.create_vault("CodeExecutionRollbackVault")

        await self.start_system()

        import core.chat.executor as chat_executor

        async def _prepared_code_execution_failure(*args, **kwargs):
            return PreparedChatExecution(
                agent=_CodeExecutionFailingAgent(vault),
                message_history=None,
                prompt_for_history="Use code_execution then fail.",
                user_prompt="Use code_execution then fail.",
                attached_image_count=0,
                model="test",
                tools=["code_execution", "file_ops_safe"],
            )

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        chat_executor._prepare_chat_execution = _prepared_code_execution_failure
        session_id = "code_execution_rollback_session"
        try:
            checkpoint = self.event_checkpoint()
            caught = None
            try:
                await execute_chat_prompt(
                    vault_name=vault.name,
                    vault_path=str(vault),
                    prompt="Use code_execution then fail.",
                    image_paths=[],
                    image_uploads=[],
                    session_id=session_id,
                    tools=["code_execution", "file_ops_safe"],
                    model="test",
                    context_template=None,
                )
            except RuntimeError as exc:
                caught = exc
            events = self.events_since(checkpoint)

            self.soft_assert(caught is not None, "Forced parent chat failure should propagate")
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
                name="task_file_mutation_recorded",
                expected={
                    "task_id": task_id,
                    "path": "notes/code-execution-write.md",
                    "operation": "write",
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
                not (Path(vault) / "notes/code-execution-write.md").exists(),
                "Failed parent task should rollback file created through code_execution",
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            await self.stop_system()
            self.teardown_scenario()
            self.assert_no_failures()
