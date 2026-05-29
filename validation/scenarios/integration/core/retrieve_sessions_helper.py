"""Integration scenario for the retrieve_sessions Monty helper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from core.chat.chat_store import ChatStore
from core.memory.session_summary import SessionSummaryStore
from validation.core.base_scenario import BaseScenario


class RetrieveSessionsHelperScenario(BaseScenario):
    """Validate retrieve_sessions selects session metadata without loading history."""

    async def test_scenario(self):
        vault = self.create_vault("RetrieveSessionsVault")
        controller = self._get_system_controller()
        system_root = str(controller._system_root)
        chat_store = ChatStore(system_root=system_root)
        summary_store = SessionSummaryStore(system_root=system_root)

        self._seed_session(chat_store, vault.name, "pending-one", title="Pending one")
        self._seed_session(chat_store, vault.name, "has-summary", title="Has summary")
        self._seed_session(chat_store, vault.name, "pending-two", title="Pending two")
        self._seed_session(chat_store, vault.name, "stale-summary", title="Stale summary", message_count=5)
        self._seed_session(chat_store, vault.name, "compacted-summary", title="Compacted summary", message_count=3)
        self._seed_session(chat_store, vault.name, "current-summary", title="Current summary", message_count=4)
        summary_store.upsert_session_summary(
            vault_name=vault.name,
            session_id="has-summary",
            title="Has summary",
            summary="Existing summary row.",
            domain="validation",
            work_product="test",
            user_intent="Validate pending summary selection.",
        )
        summary_store.upsert_session_summary(
            vault_name=vault.name,
            session_id="stale-summary",
            title="Stale summary",
            summary="Existing summary row.",
            domain="validation",
            work_product="test",
            user_intent="Validate stale summary selection.",
            metadata={"message_count": 2},
        )
        summary_store.upsert_session_summary(
            vault_name=vault.name,
            session_id="compacted-summary",
            title="Compacted summary",
            summary="Existing summary row.",
            domain="validation",
            work_product="test",
            user_intent="Validate stale summary selection after compaction.",
            metadata={"message_count": 6},
        )
        summary_store.upsert_session_summary(
            vault_name=vault.name,
            session_id="current-summary",
            title="Current summary",
            summary="Existing summary row.",
            domain="validation",
            work_product="test",
            user_intent="Validate current summary selection.",
            metadata={"message_count": 4},
        )

        self.create_file(vault, "AssistantMD/Authoring/retrieve_sessions_probe.md", WORKFLOW)

        await self.start_system()
        result = await self.run_workflow(vault, "retrieve_sessions_probe")
        self.soft_assert_equal(result.status, "completed", "Workflow should complete")

        output_path = vault / "pending-sessions.md"
        self.soft_assert(output_path.exists(), "Workflow should write pending session output")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        session_ids = {item["session_id"] for item in payload["items"]}
        self.soft_assert_equal(
            session_ids,
            {"pending-one", "pending-two", "stale-summary", "compacted-summary"},
            "retrieve_sessions pending_or_stale_summary selection should include pending and stale sessions",
        )
        self.soft_assert(
            all(item["message_count"] in {2, 3, 5} for item in payload["items"]),
            "retrieve_sessions should include message counts",
        )
        self.soft_assert(
            {
                item["session_id"]: item["summary_status"]
                for item in payload["items"]
            }
            == {
                "pending-one": "pending",
                "pending-two": "pending",
                "stale-summary": "stale",
                "compacted-summary": "stale",
            },
            "retrieve_sessions should report pending and stale summary statuses",
        )
        deltas = {
            item["session_id"]: item.get("message_count_delta")
            for item in payload["items"]
        }
        self.soft_assert_equal(
            deltas.get("stale-summary"),
            3,
            "retrieve_sessions should report positive message count deltas",
        )
        self.soft_assert_equal(
            deltas.get("compacted-summary"),
            -3,
            "retrieve_sessions should report negative message count deltas after compaction",
        )
        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    def _seed_session(
        self,
        chat_store: ChatStore,
        vault_name: str,
        session_id: str,
        *,
        title: str,
        message_count: int = 2,
    ) -> None:
        messages = []
        for index in range(message_count):
            if index % 2 == 0:
                messages.append(UserPromptPart(content=f"Question {index} for {title}"))
            else:
                messages.append(TextPart(content=f"Answer {index} for {title}"))
        chat_store.add_messages(
            session_id,
            vault_name,
            [
                ModelRequest(parts=[part])
                if isinstance(part, UserPromptPart)
                else ModelResponse(parts=[part])
                for part in messages
            ],
        )
        chat_store.set_session_title(session_id, vault_name, title)

WORKFLOW = """---
run_type: workflow
description: Probe retrieve_sessions pending_or_stale_summary selection
---
```python
import json

sessions = await retrieve_sessions(selection="pending_or_stale_summary", limit="all")
payload = {
    "selection": sessions.selection,
    "item_count": sessions.item_count,
    "items": [item.metadata for item in sessions.items],
}
await file_ops_safe(
    operation="write",
    path="pending-sessions.md",
    content=json.dumps(payload, indent=2, sort_keys=True),
)
```
"""
