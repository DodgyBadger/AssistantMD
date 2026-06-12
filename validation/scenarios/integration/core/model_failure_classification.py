"""Integration scenario for agent-safe model/API failure classification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.exceptions import ModelHTTPError

from core.chat.executor import PreparedChatExecution, execute_chat_prompt_stream
from validation.core.base_scenario import BaseScenario


class _BillingFailureStreamAgent:
    """Fake agent that raises a provider billing-style model error."""

    async def run_stream_events(self, *args, **kwargs):
        raise ModelHTTPError(
            status_code=400,
            model_name="gpt-5-mini",
            body={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Your credit balance is too low to access this provider.",
                },
            },
        )
        yield None


class ModelFailureClassificationScenario(BaseScenario):
    """Validate model provider failures become structured recovery metadata."""

    async def test_scenario(self):
        vault = self.create_vault("ModelFailureClassificationVault")

        await self.start_system()

        import core.chat.executor as chat_executor

        async def _prepared_failure(*args, **kwargs):
            return PreparedChatExecution(
                agent=_BillingFailureStreamAgent(),
                message_history=None,
                prompt_for_history="Trigger provider billing failure.",
                user_prompt="Trigger provider billing failure.",
                attached_image_count=0,
                model="gpt-mini",
                tools=[],
            )

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        chat_executor._prepare_chat_execution = _prepared_failure
        session_id = "model_failure_classification_session"
        try:
            stream = execute_chat_prompt_stream(
                vault_name=vault.name,
                vault_path=str(vault),
                prompt="Trigger provider billing failure.",
                image_paths=[],
                image_uploads=[],
                session_id=session_id,
                tools=[],
                model="gpt-mini",
                context_template=None,
            )

            chunks: list[str] = []
            caught = None
            try:
                async for chunk in stream:
                    chunks.append(chunk)
            except ModelHTTPError as exc:
                caught = exc

            assert caught is not None, "Provider model error should propagate after SSE error"
            error_payload = "\n".join(chunks)
            assert '"event": "error"' in error_payload, "Streaming should emit an error event"
            assert '"failure_kind": "billing"' in error_payload, (
                "Streaming error details should classify provider billing failures"
            )
            assert '"retryable": false' in error_payload, (
                "Billing failures should be non-retryable without user action"
            )
            assert '"http_status": 400' in error_payload, (
                "Streaming error details should expose provider HTTP status"
            )

            detail = self.call_api(
                f"/api/chat/sessions/{session_id}?vault_name={vault.name}"
            )
            assert detail.status_code == 200, "Failed chat session detail should be available"
            latest_failure = detail.json().get("latest_failure")
            assert latest_failure is not None, "Failure marker should be exposed"
            assert latest_failure.get("error_type") == "ModelHTTPError", (
                "Failure marker should preserve model error type"
            )
            assert latest_failure.get("failure_kind") == "billing", (
                "Failure marker should classify provider billing failures"
            )
            assert latest_failure.get("retryable") is False, (
                "Failure marker should mark billing failures non-retryable"
            )
            assert latest_failure.get("http_status") == 400, (
                "Failure marker should include provider HTTP status"
            )
            assert "billing" in latest_failure.get("suggested_action", "").lower(), (
                "Failure marker should tell the agent/user to check billing"
            )

            activity_log = self.call_api("/api/system/activity-log")
            assert activity_log.status_code == 200, "Activity log fetch should succeed"
            content = activity_log.json()["content"]
            assert '"failure_kind": "billing"' in content, (
                "Activity log should include model failure classification"
            )
            assert '"retryable": false' in content, (
                "Activity log should include model retryability"
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            await self.stop_system()
            self.teardown_scenario()
