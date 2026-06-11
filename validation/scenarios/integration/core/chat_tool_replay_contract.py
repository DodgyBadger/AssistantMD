"""Integration scenario for deterministic persisted chat tool replay."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from validation.core.base_scenario import BaseScenario


class ChatToolReplayContractScenario(BaseScenario):
    """Validate persisted tool replay is keyed by committed tool call IDs."""

    async def test_scenario(self):
        vault = self.create_vault("ChatToolReplayContractVault")

        await self.start_system()

        from core.chat.chat_store import ChatStore
        from core.runtime.state import get_runtime_context

        runtime = get_runtime_context()
        store = ChatStore(system_root=str(runtime.config.system_root))
        session_id = "chat_tool_replay_contract_session"

        store.add_messages(
            session_id,
            vault.name,
            [
                ModelRequest(parts=[UserPromptPart(content="Use both probe tools.")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(tool_name="probe_alpha", args={"path": "A.md"}, tool_call_id="probe-a"),
                        ToolCallPart(tool_name="probe_beta", args={"path": "B.md"}, tool_call_id="probe-b"),
                    ],
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(tool_name="probe_alpha", content="alpha result", tool_call_id="probe-a"),
                        ToolReturnPart(tool_name="probe_beta", content="beta result", tool_call_id="probe-b"),
                    ],
                ),
                ModelResponse(parts=[TextPart(content="Both probes completed.")]),
            ],
        )
        store.add_tool_event(
            session_id=session_id,
            vault_name=vault.name,
            tool_call_id="cancelled-call",
            tool_name="probe_cancelled",
            event_type="call",
            args={"path": "cancelled.md"},
        )
        store.add_tool_event(
            session_id=session_id,
            vault_name=vault.name,
            tool_call_id="probe-b",
            tool_name="probe_beta",
            event_type="call",
            args={"path": "B.md"},
        )
        store.add_tool_event(
            session_id=session_id,
            vault_name=vault.name,
            tool_call_id="probe-b",
            tool_name="probe_beta",
            event_type="result",
            result_text="beta result",
        )
        store.add_tool_event(
            session_id=session_id,
            vault_name=vault.name,
            tool_call_id="probe-a",
            tool_name="probe_alpha",
            event_type="call",
            args={"path": "A.md"},
        )
        store.add_tool_event(
            session_id=session_id,
            vault_name=vault.name,
            tool_call_id="probe-a",
            tool_name="probe_alpha",
            event_type="result",
            result_text="alpha result",
        )

        detail_response = self.call_api(
            f"/api/chat/sessions/{session_id}?vault_name={vault.name}",
        )
        assert detail_response.status_code == 200, "Session detail should load"
        detail = detail_response.json()

        message_payloads = detail["messages"]
        tool_call_message = next(
            message for message in message_payloads
            if set(message["tool_call_ids"]) == {"probe-a", "probe-b"}
        )
        tool_return_message = next(
            message for message in message_payloads
            if set(message["tool_return_ids"]) == {"probe-a", "probe-b"}
        )
        self.soft_assert(
            tool_call_message["is_tool_message"],
            "Tool-call message should be marked as a tool message",
        )
        self.soft_assert(
            tool_return_message["is_tool_message"],
            "Tool-return message should be marked as a tool message",
        )
        self.soft_assert_equal(
            tool_call_message["tool_call_ids"],
            ["probe-a", "probe-b"],
            "Tool-call IDs should preserve Pydantic message part order",
        )
        self.soft_assert_equal(
            tool_return_message["tool_return_ids"],
            ["probe-a", "probe-b"],
            "Tool-return IDs should preserve Pydantic message part order",
        )

        event_ids = [event["tool_call_id"] for event in detail["tool_events"]]
        self.soft_assert(
            "cancelled-call" not in event_ids,
            "Session detail should omit orphan diagnostic tool events",
        )
        self.soft_assert_equal(
            event_ids,
            ["probe-b", "probe-b", "probe-a", "probe-a"],
            "Session detail should preserve persisted event order for committed tool IDs",
        )
        self.soft_assert_equal(
            {event["tool_call_id"] for event in detail["tool_events"]},
            {"probe-a", "probe-b"},
            "Session detail should expose all committed tool events",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
