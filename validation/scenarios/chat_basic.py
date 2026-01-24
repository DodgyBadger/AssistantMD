"""
Basic chat scenario exercising the validation chat harness.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class TestChatBasicScenario(BaseScenario):
    """Test single chat prompt execution and transcript capture."""

    async def test_scenario(self):
        vault = self.create_vault("ChatVault")

        session_id = "session-basic"
        prompt = "Write a haiku celebrating validation frameworks."

        response = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                "vault_name": vault.name,
                "prompt": prompt,
                "session_id": session_id,
                "tools": [],
                "model": "sonnet",
                "use_conversation_history": False,
                "stream": False,
            },
        )
        assert response.status_code == 200, response.text
        data = response.data or {}

        assert data.get("session_id") == session_id, "Session ID should round-trip"
        history_path = vault / "AssistantMD" / "Chat_Sessions" / f"{session_id}.md"
        assert history_path.exists(), f"Chat history not found: {history_path}"
        history_content = history_path.read_text()
        assert prompt in history_content
        assert "haiku" in history_content

        self.teardown_scenario()
