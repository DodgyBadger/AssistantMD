"""Integration scenario for API-safe error envelopes and retry decisions."""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ApiErrorResilienceScenario(BaseScenario):
    """Validate actionable, safe API errors and retry policy primitives."""

    async def test_scenario(self):
        from core.tools.failures import classify_exception, retry_decision

        self.create_vault("ApiErrorVault")
        await self.start_system()

        missing_task = self.call_api("/api/tasks/not-a-real-task")
        self.soft_assert_equal(
            missing_task.status_code,
            404,
            "Missing task endpoint should return a typed API error",
        )
        missing_payload = missing_task.json()
        self._assert_error_envelope(
            missing_payload,
            expected_error="ExecutionTaskNotFound",
            expected_retryable=False,
        )
        self.soft_assert_equal(
            missing_payload["details"].get("task_id"),
            "not-a-real-task",
            "APIException details should preserve relevant recovery ids",
        )

        invalid_vault = self.call_api(
            "/api/workflows/file",
            params={"global_id": "bad-id"},
        )
        self.soft_assert_equal(
            invalid_vault.status_code,
            500,
            "Unexpected API exceptions should return a safe server error",
        )
        invalid_payload = invalid_vault.json()
        self._assert_error_envelope(
            invalid_payload,
            expected_error="InternalServerError",
            expected_detail_error_type="ValueError",
            expected_retryable=False,
        )
        self.soft_assert(
            "traceback" not in (invalid_payload.get("details") or {}),
            "Non-debug API error details should not expose tracebacks",
        )

        rate_limited = _http_status_error(429, retry_after="11")
        rate_classification = classify_exception(rate_limited, phase="model_request")
        rate_decision = retry_decision(
            rate_classification,
            attempt=1,
            max_attempts=3,
            base_delay_seconds=2.0,
        )
        self.soft_assert(
            rate_decision.should_retry,
            "Retry policy should allow classified rate-limit retries",
        )
        self.soft_assert_equal(
            rate_decision.delay_seconds,
            11.0,
            "Retry policy should respect numeric Retry-After",
        )
        self.soft_assert_equal(
            rate_decision.reason,
            "retry_after",
            "Retry policy should explain Retry-After decisions",
        )

        bad_request = _http_status_error(400)
        bad_classification = classify_exception(bad_request, phase="model_request")
        bad_decision = retry_decision(
            bad_classification,
            attempt=1,
            max_attempts=3,
            base_delay_seconds=2.0,
        )
        self.soft_assert(
            not bad_decision.should_retry,
            "Retry policy should not retry permanent bad requests",
        )
        self.soft_assert_equal(
            bad_decision.reason,
            "not_retryable",
            "Retry policy should explain non-retryable failures",
        )

        exhausted_decision = retry_decision(
            rate_classification,
            attempt=3,
            max_attempts=3,
            base_delay_seconds=2.0,
        )
        self.soft_assert(
            not exhausted_decision.should_retry,
            "Retry policy should stop at max attempts",
        )
        self.soft_assert_equal(
            exhausted_decision.reason,
            "max_attempts_exhausted",
            "Retry policy should explain exhausted retries",
        )

        self.teardown_scenario()
        self.assert_no_failures()

    def _assert_error_envelope(
        self,
        payload: dict,
        *,
        expected_error: str,
        expected_retryable: bool,
        expected_detail_error_type: str | None = None,
    ) -> None:
        self.soft_assert_equal(
            payload.get("success"),
            False,
            "Error responses should keep success=false",
        )
        self.soft_assert_equal(
            payload.get("error"),
            expected_error,
            "Error response should preserve stable error type",
        )
        details = payload.get("details") or {}
        self.soft_assert_equal(
            details.get("status"),
            "failed",
            "Error details should include failure status",
        )
        self.soft_assert_equal(
            details.get("error_type"),
            expected_detail_error_type or expected_error,
            "Error details should include stable error_type",
        )
        self.soft_assert_equal(
            details.get("phase"),
            "api_request",
            "Error details should include phase",
        )
        self.soft_assert_equal(
            details.get("retryable"),
            expected_retryable,
            "Error details should include retryability",
        )
        self.soft_assert(
            isinstance(details.get("suggested_action"), str)
            and details["suggested_action"].strip(),
            "Error details should include suggested_action",
        )


def _http_status_error(status_code: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.provider.test/v1/chat")
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = httpx.Response(status_code, headers=headers, request=request)
    return httpx.HTTPStatusError("synthetic provider status failure", request=request, response=response)
