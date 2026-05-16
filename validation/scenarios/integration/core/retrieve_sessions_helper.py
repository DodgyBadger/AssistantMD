"""Integration scenario for the retrieve_sessions Monty helper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from core.chat.chat_store import ChatStore
from core.memory.session_memory import SessionMemoryStore
from validation.core.base_scenario import BaseScenario


class RetrieveSessionsHelperScenario(BaseScenario):
    """Validate retrieve_sessions selects session metadata without loading history."""

    async def test_scenario(self):
        vault = self.create_vault("RetrieveSessionsVault")
        controller = self._get_system_controller()
        system_root = str(controller._system_root)
        chat_store = ChatStore(system_root=system_root)
        memory_store = SessionMemoryStore(system_root=system_root)

        self._seed_session(chat_store, vault.name, "pending-one", title="Pending one")
        self._seed_session(chat_store, vault.name, "has-memory", title="Has memory")
        self._seed_session(chat_store, vault.name, "pending-two", title="Pending two")
        memory_store.upsert_session_memory(
            vault_name=vault.name,
            session_id="has-memory",
            title="Has memory",
            summary="Existing memory row.",
            domain="validation",
            work_product="test",
            user_intent="Validate pending memory selection.",
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
            {"pending-one", "pending-two"},
            "retrieve_sessions pending_memory selection should exclude sessions with memory",
        )
        self.soft_assert(
            all(item["message_count"] == 2 for item in payload["items"]),
            "retrieve_sessions should include message counts",
        )
        self.soft_assert(
            all(item["has_memory"] is False for item in payload["items"]),
            "retrieve_sessions pending_memory items should report has_memory=false",
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
    ) -> None:
        chat_store.add_messages(
            session_id,
            vault_name,
            [
                ModelRequest(parts=[UserPromptPart(content=f"Question for {title}")]),
                ModelResponse(parts=[TextPart(content=f"Answer for {title}")]),
            ],
        )
        chat_store.set_session_title(session_id, vault_name, title)


WORKFLOW = """---
run_type: workflow
description: Probe retrieve_sessions pending_memory selection
---
```python
import json

sessions = await retrieve_sessions(selection="pending_memory", limit="all")
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
