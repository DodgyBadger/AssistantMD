"""
Integration scenario for broker-backed context assembly.

Validates structured session history access through retrieve_history(...)
plus assemble_context(...) without depending on live chat behavior.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from validation.core.base_scenario import BaseScenario


class AuthoringContextAssemblyScenario(BaseScenario):
    """Validate retrieve_history(...) and assemble_context(...) deterministically."""

    async def test_scenario(self):
        vault = self.create_vault("AuthoringContextAssemblyVault")

        await self.start_system()

        from core.authoring.runtime import WorkflowAuthoringHost, run_authoring_monty
        session_id = "context_assembly_session"
        workflow_id = f"{vault.name}/chat/{session_id}"
        now = datetime(2026, 4, 7, 12, 0, 0)

        history = [
            ModelRequest(
                parts=[UserPromptPart(content="First question")],
                run_id="run-1",
            ),
            ModelResponse(
                parts=[TextPart(content="First answer")],
                run_id="run-1",
            ),
            ModelRequest(
                parts=[UserPromptPart(content="Second question")],
                run_id="run-2",
            ),
            ModelResponse(
                parts=[TextPart(content="Second answer")],
                run_id="run-2",
            ),
        ]

        host = WorkflowAuthoringHost(
            workflow_id=workflow_id,
            vault_path=str(vault),
            reference_date=now,
            session_key=session_id,
            chat_session_id=session_id,
            message_history=history,
        )

        checkpoint = self.event_checkpoint()
        result = await run_authoring_monty(
            workflow_id=workflow_id,
            code=AUTHORING_CONTEXT_ASSEMBLY_CODE,
            host=host,
            script_name="context_assembly.py",
        )
        events = self.events_since(checkpoint)

        self.assert_event_contains(
            events,
            name="authoring_retrieve_history_completed",
            expected={
                "workflow_id": workflow_id,
                "item_count": 4,
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_assemble_context_completed",
            expected={
                "workflow_id": workflow_id,
                "message_count": 6,
                "instruction_count": 1,
            },
        )

        output = result.value
        self.soft_assert_equal(output["history_count"], 4, "Expected four retrieved history messages")
        self.soft_assert_equal(
            output["roles"],
            ["system", "user", "assistant", "user", "assistant", "user"],
            "Expected assembled context ordering to preserve instructions, history, then latest user",
        )
        self.soft_assert_equal(
            output["last_message"],
            "What should happen next?",
            "Expected latest user message appended last",
        )
        self.soft_assert(output["instruction_seen"], "Expected explicit instruction to be preserved")

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()


AUTHORING_CONTEXT_ASSEMBLY_CODE = """
history_payload = await retrieve_history(scope="session", limit="all")
assembled = await assemble_context(
    history=history_payload.items,
    instructions="Use exact text.",
    latest_user_message={"role": "user", "content": "What should happen next?"},
)

{
    "history_count": history_payload.item_count,
    "roles": [message.role for message in assembled.messages],
    "last_message": assembled.messages[-1].content,
    "instruction_seen": any("Use exact text." in message.content for message in assembled.messages),
}
"""
