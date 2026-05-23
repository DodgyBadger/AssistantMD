"""Integration scenario for the retrieve_sessions Monty helper."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from core.chat.chat_store import ChatStore
from core.memory.session_summary import SessionSummaryStore
from core.settings.store import SETTINGS_TEMPLATE, refresh_settings_cache
from validation.core.base_scenario import BaseScenario


class RetrieveSessionsHelperScenario(BaseScenario):
    """Validate retrieve_sessions selects session metadata without loading history."""

    async def test_scenario(self):
        vault = self.create_vault("RetrieveSessionsVault")
        controller = self._get_system_controller()
        system_root = str(controller._system_root)
        self._write_stale_summary_min_new_messages(controller._system_root, 2)
        chat_store = ChatStore(system_root=system_root)
        summary_store = SessionSummaryStore(system_root=system_root)

        self._seed_session(chat_store, vault.name, "pending-one", title="Pending one")
        self._seed_session(chat_store, vault.name, "has-summary", title="Has summary")
        self._seed_session(chat_store, vault.name, "pending-two", title="Pending two")
        self._seed_session(chat_store, vault.name, "stale-summary", title="Stale summary", message_count=5)
        self._seed_session(chat_store, vault.name, "minor-update", title="Minor update", message_count=4)
        self._seed_session(chat_store, vault.name, "inside-grace", title="Inside grace", message_count=5)
        summary_store.upsert_session_summary(
            vault_name=vault.name,
            session_id="has-summary",
            title="Has summary",
            summary="Existing summary row.",
            domain="validation",
            work_product="test",
            user_intent="Validate pending summary selection.",
        )
        for session_id in ("stale-summary", "minor-update", "inside-grace"):
            summary_store.upsert_session_summary(
                vault_name=vault.name,
                session_id=session_id,
                title=session_id,
                summary="Existing summary row.",
                domain="validation",
                work_product="test",
                user_intent="Validate stale summary selection.",
                metadata={"message_count": 2},
            )
        self._set_summary_updated_at(
            controller._system_root,
            vault.name,
            "stale-summary",
            datetime.now(UTC) - timedelta(hours=2),
        )
        self._set_summary_updated_at(
            controller._system_root,
            vault.name,
            "minor-update",
            datetime.now(UTC) - timedelta(hours=2),
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
            {"pending-one", "pending-two", "stale-summary", "minor-update"},
            "retrieve_sessions pending_or_stale_summary selection should include pending and stale sessions",
        )
        self.soft_assert(
            all(item["message_count"] in {2, 4, 5} for item in payload["items"]),
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
                "minor-update": "stale",
            },
            "retrieve_sessions should report pending and stale summary statuses",
        )
        stale_items = [
            item for item in payload["items"] if item["summary_status"] == "stale"
        ]
        self.soft_assert(
            all(item["stale_summary_min_new_messages"] == 2 for item in stale_items),
            "retrieve_sessions should use the configured stale summary message threshold",
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

    def _set_summary_updated_at(
        self,
        system_root: Path,
        vault_name: str,
        session_id: str,
        updated_at: datetime,
    ) -> None:
        conn = sqlite3.connect(system_root / "session_summaries.db")
        try:
            conn.execute(
                """
                UPDATE session_summaries
                SET updated_at = ?
                WHERE vault_name = ? AND session_id = ?
                """,
                (updated_at.isoformat(), vault_name, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _write_stale_summary_min_new_messages(
        self,
        system_root: Path,
        threshold: int,
    ) -> None:
        settings_path = system_root / "settings.yaml"
        raw = yaml.safe_load(SETTINGS_TEMPLATE.read_text(encoding="utf-8")) or {}
        raw["settings"]["stale_summary_min_new_messages"]["value"] = threshold
        settings_path.write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        refresh_settings_cache()


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
