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

        result = await self.run_chat_prompt(
            vault,
            prompt,
            session_id=session_id,
            tools=[],
            model="sonnet",
        )

        self.expect_equals(result.session_id, session_id, "Session ID should round-trip")
        self.expect_chat_history_exists(vault, session_id)
        self.expect_chat_history_contains(
            vault,
            session_id,
            [prompt, "haiku"],
        )

        self.teardown_scenario()
