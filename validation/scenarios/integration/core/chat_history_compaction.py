"""Integration scenario for chat history compaction primitives and API."""

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


class ChatHistoryCompactionScenario(BaseScenario):
    """Validate compaction rewrites stored history safely."""

    async def test_scenario(self):
        vault = self.create_vault("ChatHistoryCompactionVault")

        await self.start_system()

        import core.chat.compaction as compaction
        from core.chat.chat_store import ChatStore
        from core.runtime.state import get_runtime_context

        runtime = get_runtime_context()
        store = ChatStore(system_root=str(runtime.config.system_root))
        session_id = "chat_history_compaction_session"
        messages = [
            ModelRequest(parts=[UserPromptPart(content="First user decision.")]),
            ModelResponse(parts=[TextPart(content="First assistant answer.")]),
            ModelRequest(parts=[UserPromptPart(content="Please use the probe tool.")]),
            ModelResponse(parts=[ToolCallPart(tool_name="probe", args={}, tool_call_id="probe-1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="probe", content="probe result", tool_call_id="probe-1")]),
            ModelResponse(parts=[TextPart(content="Probe result handled.")]),
        ]
        store.add_messages(session_id, vault.name, messages)

        older_messages, recent_messages = compaction.split_history_for_compaction(
            messages,
            keep_recent=2,
        )
        prompt = compaction._build_summary_prompt(
            older_messages=older_messages,
            focus="Keep decisions and tool outcomes.",
        )
        assert "probe result" not in prompt, (
            "Compaction prompt should not include recent turns that will be preserved verbatim"
        )
        assert len(recent_messages) == 3, "Recent slice shifts backward to preserve tool pair"

        original_keep_recent = compaction.get_compaction_keep_recent
        original_threshold = compaction.get_compaction_token_threshold
        compaction.get_compaction_keep_recent = lambda: 2
        compaction.get_compaction_token_threshold = lambda: 1

        try:
            status_response = self.call_api(
                f"/api/chat/sessions/{session_id}/compaction-status?vault_name={vault.name}"
            )
            assert status_response.status_code == 200, "Compaction status endpoint succeeds"
            status_payload = status_response.json()
            assert status_payload["messages_before"] == 6, "Status reports current message count"
            assert status_payload["recommended"] is True, "Status recommends compaction past threshold"

            async def _summary_stub(*args, **kwargs):
                return "Preserve first decision and the probe result outcome."

            original_generate_summary = compaction._generate_compaction_summary
            compaction._generate_compaction_summary = _summary_stub
            try:
                compact_response = self.call_api(
                    f"/api/chat/sessions/{session_id}/compact",
                    method="POST",
                    data={
                        "vault_name": vault.name,
                        "focus": "Keep decisions and tool outcomes.",
                        "export_before": False,
                    },
                )
            finally:
                compaction._generate_compaction_summary = original_generate_summary
        finally:
            compaction.get_compaction_keep_recent = original_keep_recent
            compaction.get_compaction_token_threshold = original_threshold

        assert compact_response.status_code == 200, "Compaction endpoint succeeds"
        compact_payload = compact_response.json()
        assert compact_payload["messages_before"] == 6, "Compaction reports original count"
        assert compact_payload["messages_after"] == 4, "Compaction keeps summary plus adjusted recent slice"
        assert compact_payload["kept_recent"] == 3, "Recent slice shifts backward to preserve tool pair"
        assert compact_payload["export_created"] is False, "Compaction honors export_before false"

        detail = self.call_api(f"/api/chat/sessions/{session_id}?vault_name={vault.name}")
        assert detail.status_code == 200, "Session detail endpoint succeeds after compaction"
        detail_messages = detail.json()["messages"]
        assert len(detail_messages) == 4, "Canonical history is rewritten"
        assert detail_messages[0]["role"] == "system", "First message is system-maintained summary"
        assert "AssistantMD compacted chat history" in detail_messages[0]["content"], (
            "Summary marker is persisted"
        )
        assert detail_messages[1]["content"].startswith("[probe] (tool call)"), (
            "Tool call remains in recent history"
        )
        assert "probe result" in detail_messages[2]["content"], (
            "Tool result remains paired with the call"
        )
        metadata = store.get_session_metadata(session_id, vault.name)
        assert "last_compaction" in metadata, "Compaction audit metadata is recorded"

        await self.stop_system()
        self.teardown_scenario()
