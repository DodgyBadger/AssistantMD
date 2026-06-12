"""Integration scenario for structured tool failure envelopes."""

import sys
from pathlib import Path

import httpx
from pydantic_ai.messages import ToolReturn

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class StructuredToolFailureScenario(BaseScenario):
    """Validate retryable/permanent/configuration failure metadata for tools."""

    async def test_scenario(self):
        from core.tools.failures import classify_exception
        import core.tools.web_search_duckduckgo as duck_module
        import core.tools.web_search_tavily as tavily_module

        http_error = _http_status_error(503, retry_after="7")
        classification = classify_exception(http_error, phase="web_search")
        self.soft_assert_equal(
            classification.failure_kind,
            "provider_unavailable",
            "HTTP 5xx should be classified as provider_unavailable",
        )
        self.soft_assert(
            classification.retryable,
            "HTTP 5xx should be retryable",
        )
        self.soft_assert_equal(
            classification.retry_after,
            "7",
            "Retry-After should be preserved when present",
        )

        original_ddgs = duck_module.DDGS
        original_secret = tavily_module.get_secret_value
        original_client = tavily_module.httpx.Client
        try:
            duck_module.DDGS = _TimeoutDuckDuckGo
            duck_result = duck_module.WebSearchDuckDuckGo.get_tool().function(query="assistantmd")
            self._assert_failure_metadata(
                duck_result,
                expected={
                    "tool_name": "web_search_duckduckgo",
                    "status": "failed",
                    "failure_kind": "transient_provider",
                    "retryable": True,
                    "phase": "web_search",
                    "query": "assistantmd",
                },
            )

            tavily_module.get_secret_value = lambda _name: "test-key"
            tavily_module.httpx.Client = _FailingTavilyClient
            tavily_result = tavily_module.WebSearchTavily.get_tool().function(query="assistantmd")
            self._assert_failure_metadata(
                tavily_result,
                expected={
                    "tool_name": "web_search_tavily",
                    "status": "failed",
                    "failure_kind": "provider_unavailable",
                    "retryable": True,
                    "phase": "web_search",
                    "http_status": 503,
                    "retry_after": "5",
                    "query": "assistantmd",
                },
            )
        finally:
            duck_module.DDGS = original_ddgs
            tavily_module.get_secret_value = original_secret
            tavily_module.httpx.Client = original_client

        self.teardown_scenario()
        self.assert_no_failures()

    def _assert_failure_metadata(
        self,
        result,
        *,
        expected: dict[str, object],
    ) -> None:
        self.soft_assert(
            isinstance(result, ToolReturn),
            "Tool failure should return a ToolReturn envelope",
        )
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        for key, value in expected.items():
            self.soft_assert_equal(
                metadata.get(key),
                value,
                f"Failure metadata should include {key}",
            )
        self.soft_assert(
            isinstance(result.return_value, str) and result.return_value.strip(),
            "Tool failure should keep concise model-readable text",
        )
        self.soft_assert(
            "suggested_action" in metadata,
            "Tool failure metadata should include suggested_action",
        )


class _TimeoutDuckDuckGo:
    def __init__(self, *, timeout: int):
        self.timeout = timeout

    def text(self, **_kwargs):
        raise TimeoutError("timeout while searching")


class _FailingTavilyClient:
    def __init__(self, *, timeout: float):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        return _FailingTavilyResponse()


class _FailingTavilyResponse:
    def raise_for_status(self):
        raise _http_status_error(503, retry_after="5")


def _http_status_error(status_code: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.tavily.com/search")
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = httpx.Response(status_code, headers=headers, request=request)
    return httpx.HTTPStatusError("synthetic status failure", request=request, response=response)
