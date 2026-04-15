"""
Integration scenario validating the durable chat session persistence contract.

Exercises a real chat turn, persists a normal tool result, restarts the system,
and verifies both SQLite-backed session history and structured tool-event rows.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ChatSessionPersistenceContractScenario(BaseScenario):
    """Validate persisted chat messages and tool events across restart."""

    async def test_scenario(self):
        vault = self.create_vault("ChatSessionPersistenceContractVault")

        await self.start_system()

        import core.chat.executor as chat_executor
        from core.authoring.runtime import WorkflowAuthoringHost, run_authoring_monty
        from core.constants import ASSISTANTMD_ROOT_DIR, CHAT_SESSIONS_DIR
        from core.runtime.state import get_runtime_context
        from pydantic_ai.models.test import TestModel

        session_id = "chat_session_persistence_contract_session"

        async def session_probe() -> str:
            return "SESSION_PROBE_RESULT"

        def _patched_prepare_agent_config(vault_name, vault_path, tools, model):
            del vault_name, vault_path, tools, model
            return (
                "You must call the session_probe tool before responding.",
                "",
                TestModel(),
                [session_probe],
            )

        original_prepare_agent_config = chat_executor._prepare_agent_config
        chat_executor._prepare_agent_config = _patched_prepare_agent_config
        try:
            response = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Use the session_probe tool and then answer briefly.",
                    "session_id": session_id,
                    "tools": ["session_probe"],
                    "model": "test",
                },
            )
            assert response.status_code == 200, "Chat execution should succeed for persistence contract coverage"

            payload = response.json()
            self.soft_assert_equal(payload["session_id"], session_id, "Expected stable explicit session id")
            self.soft_assert(
                "SESSION_PROBE_RESULT" in payload["response"],
                "Expected assistant response to reflect the tool result",
            )

            runtime = get_runtime_context()
            chat_sessions_db = Path(runtime.config.system_root) / "chat_sessions.db"
            assert chat_sessions_db.exists(), "Chat session persistence DB should be created"

            with sqlite3.connect(chat_sessions_db) as conn:
                session_row = conn.execute(
                    """
                    SELECT session_id, vault_name
                    FROM chat_sessions
                    WHERE session_id = ? AND vault_name = ?
                    """,
                    (session_id, vault.name),
                ).fetchone()
                assert session_row is not None, "Chat session row should be persisted"

                message_rows = conn.execute(
                    """
                    SELECT role, content_text
                    FROM chat_messages
                    WHERE session_id = ? AND vault_name = ?
                    ORDER BY sequence_index ASC
                    """,
                    (session_id, vault.name),
                ).fetchall()
                self.soft_assert(
                    len(message_rows) >= 2,
                    "Expected persisted provider-native chat messages for the completed turn",
                )
                self.soft_assert(
                    any("Use the session_probe tool and then answer briefly." in str(row[1] or "") for row in message_rows),
                    "Persisted chat messages should include the original user prompt",
                )
                self.soft_assert(
                    any("SESSION_PROBE_RESULT" in str(row[1] or "") for row in message_rows),
                    "Persisted chat messages should include the resulting assistant/tool content",
                )

                tool_event_rows = conn.execute(
                    """
                    SELECT event_type, tool_name, result_text, artifact_ref
                    FROM chat_tool_events
                    WHERE session_id = ? AND vault_name = ?
                    ORDER BY id ASC
                    """,
                    (session_id, vault.name),
                ).fetchall()

            self.soft_assert_equal(
                [row[0] for row in tool_event_rows],
                ["call", "result"],
                "Expected normal tool execution to persist call and result events",
            )
            self.soft_assert(
                all(row[1] == "session_probe" for row in tool_event_rows),
                "Persisted tool events should record the originating tool name",
            )
            result_rows = [row for row in tool_event_rows if row[0] == "result"]
            assert result_rows, "Expected a persisted tool result row"
            self.soft_assert_equal(
                result_rows[0][2],
                "SESSION_PROBE_RESULT",
                "Persisted tool result row should retain the tool output",
            )
            self.soft_assert_equal(
                result_rows[0][3],
                None,
                "Non-overflow tool results should not create an artifact ref",
            )

            transcript = (
                Path(vault)
                / ASSISTANTMD_ROOT_DIR
                / CHAT_SESSIONS_DIR
                / f"{session_id}.md"
            )
            assert transcript.exists(), "Chat transcript should be written for the persisted session"
            transcript_text = transcript.read_text(encoding="utf-8")
            self.soft_assert(
                "**User:**" in transcript_text and "**Assistant:**" in transcript_text,
                "Transcript should contain persisted user and assistant sections",
            )
            self.soft_assert(
                "Use the session_probe tool and then answer briefly." in transcript_text,
                "Transcript should include the persisted user prompt",
            )

            await self.restart_system()

            workflow_id = f"{vault.name}/chat/{session_id}"
            host = WorkflowAuthoringHost(
                workflow_id=workflow_id,
                vault_path=str(vault),
                session_key=session_id,
                chat_session_id=session_id,
                message_history=[],
            )
            checkpoint = self.event_checkpoint()
            result = await run_authoring_monty(
                workflow_id=workflow_id,
                code=CHAT_SESSION_PERSISTENCE_CONTRACT_CODE,
                host=host,
                script_name="chat_session_persistence_contract.py",
            )
            events = self.events_since(checkpoint)

            self.assert_event_contains(
                events,
                name="authoring_call_tool_completed",
                expected={
                    "workflow_id": workflow_id,
                    "tool": "memory_ops",
                },
            )

            output = result.value
            self.soft_assert_equal(
                output["source"],
                "sqlite_chat_sessions",
                "Expected memory_ops to rehydrate from the persisted SQLite chat store after restart",
            )
            self.soft_assert_equal(
                output["history_source"],
                "chat_messages",
                "Expected get_history metadata to identify canonical chat message storage",
            )
            self.soft_assert_equal(
                output["history_message_filter"],
                "all",
                "Expected default get_history retrieval to preserve the full canonical message timeline",
            )
            self.soft_assert_equal(
                output["tool_only_count"],
                2,
                "Expected get_history(message_filter='only_tools') to expose the canonical tool-call and tool-return messages",
            )
            self.soft_assert(
                output["tool_only_message_types"] == ["ModelResponse", "ModelRequest"],
                "Expected tool-only history filtering to retain ordered provider-native tool messages",
            )
            self.soft_assert_equal(
                output["tool_event_source"],
                "sqlite_chat_sessions",
                "Expected explicit tool-event retrieval to use the persisted SQLite chat store after restart",
            )
            self.soft_assert(
                output["item_count"] >= 2,
                "Expected restarted memory_ops history to contain persisted session messages",
            )
            self.soft_assert(
                output["last_content"],
                "Expected restarted memory_ops history to include a final persisted message",
            )
            self.soft_assert_equal(
                output["tool_event_count"],
                2,
                "Expected restarted memory_ops tool-event retrieval to return call and result rows",
            )
            self.soft_assert_equal(
                output["tool_event_types"],
                ["call", "result"],
                "Expected restarted memory_ops tool-event retrieval ordering to remain stable",
            )
            self.soft_assert_equal(
                output["tool_result_text"],
                "SESSION_PROBE_RESULT",
                "Expected restarted memory_ops tool-event retrieval to expose the persisted tool result",
            )
        finally:
            chat_executor._prepare_agent_config = original_prepare_agent_config
            await self.stop_system()
            self.teardown_scenario()
            self.assert_no_failures()


CHAT_SESSION_PERSISTENCE_CONTRACT_CODE = """
import json

history = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": "all"},
)
payload = json.loads(history.output)
tool_only_history = await call_tool(
    name="memory_ops",
    arguments={
        "operation": "get_history",
        "scope": "session",
        "limit": "all",
        "message_filter": "only_tools",
    },
)
tool_only_payload = json.loads(tool_only_history.output)
tool_events = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_tool_events", "scope": "session", "limit": "all"},
)
tool_events_payload = json.loads(tool_events.output)

{
    "source": payload["source"],
    "item_count": payload["item_count"],
    "last_content": payload["items"][-1]["content"] if payload["items"] else "",
    "history_source": payload.get("metadata", {}).get("canonical_source", ""),
    "history_message_filter": payload.get("metadata", {}).get("message_filter", ""),
    "tool_only_count": tool_only_payload["item_count"],
    "tool_only_message_types": [item["message_type"] for item in tool_only_payload["items"]],
    "tool_event_source": tool_events_payload["source"],
    "tool_event_count": tool_events_payload["item_count"],
    "tool_event_types": [item["event_type"] for item in tool_events_payload["items"]],
    "tool_result_text": (
        [item["result_text"] for item in tool_events_payload["items"] if item["event_type"] == "result"] or [""]
    )[0],
}
"""
