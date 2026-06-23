"""Integration scenario for chat reasoning-part persistence policy."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart

from core.chat.chat_store import ChatStore
from validation.core.base_scenario import BaseScenario


class ChatReasoningHistoryPolicyScenario(BaseScenario):
    """Validate reasoning parts are transient by default and opt-in persistable."""

    async def test_scenario(self):
        vault = self.create_vault("ChatReasoningHistoryPolicyVault")
        await self.start_system()

        store = ChatStore(system_root=str(self._get_system_controller()._system_root))

        default_session_id = "reasoning-default"
        store.add_messages(
            default_session_id,
            vault.name,
            [self._response_with_reasoning()],
        )

        default_history = store.get_history(default_session_id, vault.name) or []
        self.soft_assert_equal(
            self._thinking_part_count(default_history),
            0,
            "Default chat persistence should drop reasoning parts",
        )
        self.soft_assert(
            self._has_visible_text(default_history),
            "Default chat persistence should preserve visible assistant text",
        )
        self.soft_assert(
            self._has_tool_call(default_history),
            "Default chat persistence should preserve tool call parts",
        )

        update_setting = self.call_api(
            "/api/system/settings/general/persist_model_reasoning_parts",
            method="PUT",
            data={"value": "true"},
        )
        self.soft_assert_equal(
            update_setting.status_code,
            200,
            "Reasoning persistence setting should be editable",
        )

        opt_in_session_id = "reasoning-opt-in"
        store.add_messages(
            opt_in_session_id,
            vault.name,
            [self._response_with_reasoning()],
        )

        opt_in_history = store.get_history(opt_in_session_id, vault.name) or []
        self.soft_assert_equal(
            self._thinking_part_count(opt_in_history),
            1,
            "Opt-in chat persistence should preserve reasoning parts",
        )
        self.soft_assert(
            self._has_visible_text(opt_in_history),
            "Opt-in chat persistence should preserve visible assistant text",
        )
        self.soft_assert(
            self._has_tool_call(opt_in_history),
            "Opt-in chat persistence should preserve tool call parts",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    def _response_with_reasoning(self) -> ModelResponse:
        return ModelResponse(
            parts=[
                ThinkingPart(
                    content="private reasoning summary",
                    id="reasoning_content",
                    provider_name="deepseek",
                ),
                TextPart(content="Visible answer."),
                ToolCallPart(
                    tool_name="probe",
                    args={"value": 1},
                    tool_call_id="probe-call",
                ),
            ],
            provider_name="deepseek",
        )

    def _thinking_part_count(self, history) -> int:
        return sum(
            1
            for message in history
            for part in getattr(message, "parts", [])
            if isinstance(part, ThinkingPart)
        )

    def _has_visible_text(self, history) -> bool:
        return any(
            isinstance(part, TextPart) and part.content == "Visible answer."
            for message in history
            for part in getattr(message, "parts", [])
        )

    def _has_tool_call(self, history) -> bool:
        return any(
            isinstance(part, ToolCallPart) and part.tool_call_id == "probe-call"
            for message in history
            for part in getattr(message, "parts", [])
        )
