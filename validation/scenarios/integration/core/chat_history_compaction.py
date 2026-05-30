"""Integration scenario for chat history compaction primitives and API."""

import sqlite3
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
        from core.chat.history_service import ChatHistoryContext, ChatHistoryService
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
        assert store.get_message_count(session_id, vault.name, mode="raw") == 6, (
            "Raw count starts with seeded messages"
        )
        assert store.get_message_count(session_id, vault.name) == 6, (
            "Effective count matches raw count before compaction"
        )
        assert store.get_session_history_revision(session_id, vault.name) == 1, (
            "Initial raw message append advances session history revision"
        )

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
                second_compact_response = self.call_api(
                    f"/api/chat/sessions/{session_id}/compact",
                    method="POST",
                    data={
                        "vault_name": vault.name,
                        "focus": "Keep the compacted decision and current tool outcome.",
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

        raw_messages = store.get_stored_messages(session_id, vault.name, mode="raw")
        assert len(raw_messages) == 6, "Compaction preserves original raw chat_messages rows"
        assert raw_messages[0].content_text == "First user decision.", (
            "Raw archival history still includes pre-compaction messages"
        )

        effective_messages = store.get_stored_messages(session_id, vault.name)
        assert len(effective_messages) == 4, "Default stored-message reads return effective history"
        assert effective_messages[0].role == "system", "Effective history starts with summary"
        assert "AssistantMD compacted chat history" in effective_messages[0].content_text, (
            "Effective summary marker is reconstructed from checkpoint"
        )
        assert effective_messages[1].content_text.startswith("[probe] (tool call)"), (
            "Effective history preserves recent tool call"
        )
        assert "probe result" in effective_messages[2].content_text, (
            "Effective history preserves recent tool result"
        )
        provider_history = store.get_history(session_id, vault.name)
        assert provider_history is not None and len(provider_history) == 4, (
            "Provider-native history defaults to effective replay"
        )

        detail = self.call_api(f"/api/chat/sessions/{session_id}?vault_name={vault.name}")
        assert detail.status_code == 200, "Session detail endpoint succeeds after compaction"
        detail_messages = detail.json()["messages"]
        assert len(detail_messages) == 4, "Session detail shows effective history"
        assert detail_messages[0]["role"] == "system", "First message is system-maintained summary"
        assert "AssistantMD compacted chat history" in detail_messages[0]["content"], (
            "Summary marker is exposed through effective replay"
        )
        assert detail_messages[1]["content"].startswith("[probe] (tool call)"), (
            "Tool call remains in recent history"
        )
        assert "probe result" in detail_messages[2]["content"], (
            "Tool result remains paired with the call"
        )
        metadata = store.get_session_metadata(session_id, vault.name)
        assert "last_compaction" in metadata, "Compaction audit metadata is recorded"

        checkpoint = store.get_latest_compaction_checkpoint(session_id, vault.name)
        assert checkpoint is not None, "Compaction records a replay checkpoint"
        assert checkpoint.last_message_sequence_index == 5, (
            "Checkpoint records the raw message high-water mark"
        )

        migration_conn = sqlite3.connect(runtime.config.system_root / "chat_sessions.db")
        try:
            migration_rows = migration_conn.execute(
                """
                SELECT version
                FROM schema_migrations
                WHERE namespace = 'chat_sessions'
                ORDER BY version
                """
            ).fetchall()
        finally:
            migration_conn.close()
        assert [row[0] for row in migration_rows] == [1], (
            "Chat checkpoint migration is recorded in schema_migrations"
        )

        assert second_compact_response.status_code == 200, "Second compaction endpoint succeeds"
        second_payload = second_compact_response.json()
        assert second_payload["messages_before"] == 4, (
            "Second compaction reads latest effective history, not raw archival history"
        )
        assert store.get_message_count(session_id, vault.name, mode="raw") == 6, (
            "Second compaction still preserves raw rows"
        )
        assert store.get_message_count(session_id, vault.name) == 4, (
            "Second compaction keeps default effective history compacted"
        )
        assert store.get_session_history_revision(session_id, vault.name) == 3, (
            "Each compaction advances session history revision"
        )

        store.add_messages(
            session_id,
            vault.name,
            [ModelRequest(parts=[UserPromptPart(content="Post-compaction follow-up.")])],
        )
        assert store.get_message_count(session_id, vault.name, mode="raw") == 7, (
            "Post-compaction turns append to raw history"
        )
        assert store.get_session_history_revision(session_id, vault.name) == 4, (
            "Post-compaction raw append advances session history revision"
        )
        replay_messages = store.get_stored_messages(session_id, vault.name)
        assert len(replay_messages) == 5, (
            "Effective replay includes latest checkpoint replacement plus appended raw turn"
        )
        assert replay_messages[-1].content_text == "Post-compaction follow-up.", (
            "Post-checkpoint raw message appears after checkpoint replacement"
        )

        broker_history = ChatHistoryService(chat_store=store).get_conversation_history(
            context=ChatHistoryContext(session_id=session_id, vault_name=vault.name),
            scope="session",
            session_id=session_id,
            limit="all",
        )
        assert broker_history.item_count == 5, (
            "History broker returns effective history after compaction"
        )
        assert all(item.content != "First user decision." for item in broker_history.items), (
            "History broker does not expose pre-checkpoint raw messages by default"
        )

        await self.stop_system()
        self.teardown_scenario()
