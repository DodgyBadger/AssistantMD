"""
Integration scenario for the delegate tool.

Validates delegate as both an LLM-facing chat tool (via patched executor)
and as a Monty direct tool (via workflow runs). Asserts on stable validation
events at decision boundaries and on final output artifacts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from validation.core.base_scenario import BaseScenario


class DelegateToolScenario(BaseScenario):
    """Validate delegate tool behavior via stable validation events and output artifacts."""

    async def test_scenario(self):
        vault = self.create_vault("DelegateToolVault")
        self.create_file(vault, "notes/content.md", "DELEGATE_CONTENT")
        self.copy_files("validation/templates/files/test_image.jpg", vault, "images")
        self.create_file(
            vault,
            "notes/with-image.md",
            "Review this embedded image.\n\n![Example](../images/test_image.jpg)\n",
        )

        await self.start_system()

        configured_delegate_limit = 12
        configured_delegate_timeout = 90
        delegate_limit_update = self.call_api(
            "/api/system/settings/general/delegate_tool_calls_limit",
            method="PUT",
            data={"value": str(configured_delegate_limit)},
        )
        assert delegate_limit_update.status_code == 200, "Delegate tool-call limit setting updates"
        delegate_timeout_update = self.call_api(
            "/api/system/settings/general/delegate_timeout_seconds",
            method="PUT",
            data={"value": str(configured_delegate_timeout)},
        )
        assert delegate_timeout_update.status_code == 200, "Delegate timeout setting updates"

        import core.chat.executor as chat_executor
        from pydantic_ai.models.test import TestModel

        current_case = {"name": "basic"}

        class _DelegateForcingModel(TestModel):
            def __init__(self):
                super().__init__(call_tools=["delegate"])

            def gen_tool_args(self, tool_def):
                if getattr(tool_def, "name", "") != "delegate":
                    return super().gen_tool_args(tool_def)
                case = current_case["name"]
                if case == "basic":
                    return {"prompt": "Reply with DELEGATE_OK.", "model": "test"}
                if case == "forbidden_stripping":
                    return {
                        "prompt": "Use your tools.",
                        "model": "test",
                        "tools": ["file_ops_safe", "delegate", "code_execution"],
                    }
                if case == "child_tools":
                    return {
                        "prompt": "List available notes.",
                        "model": "test",
                        "tools": ["file_ops_safe"],
                    }
                if case == "limit_failure":
                    return {"prompt": "Exceed child usage limits.", "model": "test"}
                if case == "model_request_limit_failure":
                    return {"prompt": "Exceed child model request usage limits.", "model": "test"}
                raise AssertionError(f"Unexpected delegate case: {case}")

        def _patched_prepare_agent_config(vault_name, vault_path, tools, model, thinking=None):
            del vault_name, vault_path, tools, model, thinking
            from core.authoring.shared.tool_binding import resolve_tool_binding
            binding = resolve_tool_binding(["delegate"], vault_path=str(vault))
            return (
                "You must call delegate before responding.",
                binding.tool_instructions,
                _DelegateForcingModel(),
                binding.tool_functions,
            )

        original_prepare = chat_executor._prepare_agent_config
        chat_executor._prepare_agent_config = _patched_prepare_agent_config
        import core.tools.delegate as delegate_module

        original_create_agent = delegate_module.create_agent

        class _FailingChildAgent:
            def __init__(self, error: Exception):
                self.error = error

            def instructions(self, *_args, **_kwargs):
                return None

            async def run(self, *_args, **_kwargs):
                raise AssertionError("delegate child agents must use streaming model calls")

            def run_stream(self, *_args, **_kwargs):
                error = self.error

                class _FailingStream:
                    async def __aenter__(self):
                        raise error

                    async def __aexit__(self, exc_type, exc, tb):
                        return False

                return _FailingStream()

        class _StreamingChildRun:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def stream_output(self, *, debounce_by=None):
                yield "streamed delegate output"

            async def get_output(self):
                return "streamed delegate output"

            def all_messages(self):
                return []

        class _StreamingChildAgent:
            def instructions(self, *_args, **_kwargs):
                return None

            async def run(self, *_args, **_kwargs):
                raise AssertionError("delegate child agents must use streaming model calls")

            def run_stream(self, *_args, **_kwargs):
                return _StreamingChildRun()

        async def _streaming_create_agent(*_args, **_kwargs):
            return _StreamingChildAgent()

        async def _assert_delegate_uses_streaming() -> None:
            from core.authoring.helpers.runtime_common import (
                invoke_bound_tool,
                normalize_tool_result,
            )
            from core.authoring.shared.tool_binding import resolve_tool_binding

            binding = resolve_tool_binding(["delegate"], vault_path=str(vault))
            delegate_module.create_agent = _streaming_create_agent
            try:
                result = await invoke_bound_tool(
                    binding.tool_functions[0],
                    tool_name="delegate",
                    arguments={"prompt": "Stream child delegate.", "model": "test"},
                    run_buffers={},
                    session_buffers={},
                    session_id="delegate_streaming_transport",
                    vault_name=vault.name,
                )
            finally:
                delegate_module.create_agent = original_create_agent
            tool_result = normalize_tool_result(
                "delegate",
                result,
                vault_path=str(vault),
            )
            self.soft_assert_equal(
                tool_result.return_value,
                "streamed delegate output",
                "Delegate should collect streamed child-agent output",
            )

        await _assert_delegate_uses_streaming()

        async def _patched_create_agent(*args, **kwargs):
            if current_case["name"] == "limit_failure":
                return _FailingChildAgent(
                    UsageLimitExceeded("The next tool call(s) would exceed the tool_calls_limit")
                )
            if current_case["name"] == "model_request_limit_failure":
                return _FailingChildAgent(
                    UsageLimitExceeded("The next request would exceed the request_limit of 75")
                )
            return await original_create_agent(*args, **kwargs)

        delegate_module.create_agent = _patched_create_agent
        try:
            # --- Basic: delegate fires and completes ---
            checkpoint = self.event_checkpoint()
            basic = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "Run a basic delegate call.",
                    "session_id": "delegate_basic",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert basic["start_response"].status_code == 200, "Basic delegate chat task should start"
            assert basic["terminal_event"].get("event") == "done", "Basic delegate call should succeed"
            basic_events = self.events_since(checkpoint)

            self.assert_event_contains(
                basic_events,
                name="delegate_started",
                expected={
                    "workflow_id": "delegate_basic",
                    "model": "test",
                    "max_tool_calls": configured_delegate_limit,
                    "timeout_seconds": configured_delegate_timeout,
                },
            )
            self.assert_event_contains(
                basic_events,
                name="delegate_completed",
                expected={
                    "workflow_id": "delegate_basic",
                    "model": "test",
                    "max_tool_calls": configured_delegate_limit,
                    "timeout_seconds": configured_delegate_timeout,
                },
            )
            self.soft_assert(
                "failed:" not in basic["text"].lower(),
                "Basic delegate call should not produce a Monty failure response",
            )

            # --- Forbidden tool stripping: delegate and code_execution removed ---
            current_case["name"] = "forbidden_stripping"
            checkpoint = self.event_checkpoint()
            stripping = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "Test forbidden tool stripping.",
                    "session_id": "delegate_forbidden_stripping",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert stripping["start_response"].status_code == 200, (
                "Forbidden tool stripping chat task should start"
            )
            assert stripping["terminal_event"].get("event") == "done", (
                "Forbidden tool stripping call should succeed"
            )
            stripping_events = self.events_since(checkpoint)

            self.assert_event_contains(
                stripping_events,
                name="delegate_started",
                expected={
                    "workflow_id": "delegate_forbidden_stripping",
                    "tool_names": ["file_ops_safe"],
                    "stripped_tools": ["code_execution", "delegate"],
                },
            )
            self.assert_event_contains(
                stripping_events,
                name="delegate_completed",
                expected={"workflow_id": "delegate_forbidden_stripping"},
            )

            # --- Child tool binding: delegate_tool_binding_resolved fires ---
            current_case["name"] = "child_tools"
            checkpoint = self.event_checkpoint()
            child_tools = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "Test delegate with child tools.",
                    "session_id": "delegate_child_tools",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert child_tools["start_response"].status_code == 200, (
                "Delegate with child tools chat task should start"
            )
            assert child_tools["terminal_event"].get("event") == "done", (
                "Delegate with child tools should succeed"
            )
            child_events = self.events_since(checkpoint)

            self.assert_event_contains(
                child_events,
                name="delegate_tool_binding_resolved",
                expected={
                    "workflow_id": "delegate_child_tools",
                    "requested": ["file_ops_safe"],
                },
            )
            self.assert_event_contains(
                child_events,
                name="delegate_completed",
                expected={"workflow_id": "delegate_child_tools"},
            )

            # --- Bounded child failures return tool output instead of aborting parent chat ---
            current_case["name"] = "limit_failure"
            checkpoint = self.event_checkpoint()
            limit_failure = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "Test delegate tool-call limit handling.",
                    "session_id": "delegate_limit_failure",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert limit_failure["start_response"].status_code == 200, (
                "Delegate limit failure chat task should start"
            )
            assert limit_failure["terminal_event"].get("event") == "done", (
                "Delegate limit failure should not abort chat"
            )
            limit_events = self.events_since(checkpoint)
            self.assert_event_contains(
                limit_events,
                name="delegate_failed",
                expected={
                    "workflow_id": "delegate_limit_failure",
                    "error_type": "UsageLimitExceeded",
                    "failure_kind": "execution_limit",
                    "retryable": False,
                    "limit_kind": "tool_calls",
                    "limit_setting": "delegate_tool_calls_limit",
                },
            )
            self.soft_assert(
                "tool-call limit" in limit_failure["text"],
                "Delegate limit failure should return actionable text to the parent agent",
            )
            self.soft_assert(
                "goal_ops" in limit_failure["text"],
                "Delegate limit failure should instruct parent to checkpoint before continuing",
            )

            current_case["name"] = "model_request_limit_failure"
            model_request_limit_failure = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "Test delegate model-request limit handling.",
                    "session_id": "delegate_model_request_limit_failure",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert model_request_limit_failure["start_response"].status_code == 200, (
                "Delegate model-request limit failure chat task should start"
            )
            assert model_request_limit_failure["terminal_event"].get("event") == "done", (
                "Delegate model-request limit failure should not abort chat"
            )
            request_limit_context = delegate_module._delegate_usage_limit_context(
                UsageLimitExceeded("The next request would exceed the request_limit of 75"),
                max_tool_calls=configured_delegate_limit,
            )
            self.soft_assert_equal(
                request_limit_context["limit_kind"],
                "model_requests",
                "Delegate request-limit context should classify model-request limits",
            )
            self.soft_assert_equal(
                request_limit_context["limit_setting"],
                "delegate_model_requests_limit",
                "Delegate request-limit context should identify the controlling setting",
            )
            self.soft_assert(
                "model-request limit" in model_request_limit_failure["text"],
                "Delegate request-limit failure should use model-request wording",
            )
            self.soft_assert(
                "goal_ops" in model_request_limit_failure["text"],
                "Delegate request-limit failure should instruct parent to checkpoint before continuing",
            )

            from core.authoring.helpers.runtime_common import (
                invoke_bound_tool,
                normalize_tool_result,
            )
            from core.authoring.shared.tool_binding import resolve_tool_binding

            checkpoint = self.event_checkpoint()
            timeout_binding = resolve_tool_binding(["delegate"], vault_path=str(vault))

            async def _timeout_create_agent(*_args, **_kwargs):
                return _FailingChildAgent(TimeoutError())

            delegate_module.create_agent = _timeout_create_agent
            try:
                timeout_result = await invoke_bound_tool(
                    timeout_binding.tool_functions[0],
                    tool_name="delegate",
                    arguments={"prompt": "Exceed child timeout.", "model": "test"},
                    run_buffers={},
                    session_buffers={},
                    session_id="delegate_timeout_failure",
                    vault_name=vault.name,
                )
            finally:
                delegate_module.create_agent = _patched_create_agent
            timeout_tool_result = normalize_tool_result(
                "delegate",
                timeout_result,
                vault_path=str(vault),
            )
            self.soft_assert_equal(
                timeout_tool_result.metadata.get("status"),
                "failed",
                "Delegate timeout should return a failed tool result",
            )
            self.soft_assert_equal(
                timeout_tool_result.metadata.get("failure_kind"),
                "delegate_timeout",
                "Delegate timeout metadata should classify the failure",
            )
            self.soft_assert_equal(
                timeout_tool_result.metadata.get("retryable"),
                False,
                "Delegate timeout metadata should tell the caller not to retry the same broad delegate",
            )
            timeout_events = self.events_since(checkpoint)
            self.assert_event_contains(
                timeout_events,
                name="delegate_started",
                expected={"workflow_id": "delegate_timeout_failure"},
            )
            self.soft_assert(
                "timeout" in timeout_tool_result.return_value,
                "Delegate timeout should return actionable text",
            )

            async def _billing_failure_create_agent(*_args, **_kwargs):
                return _FailingChildAgent(
                    ModelHTTPError(
                        status_code=400,
                        model_name="gpt-5-mini",
                        body={
                            "error": {
                                "message": "Your credit balance is too low for this request.",
                            },
                        },
                    )
                )

            delegate_module.create_agent = _billing_failure_create_agent
            try:
                billing_result = await invoke_bound_tool(
                    timeout_binding.tool_functions[0],
                    tool_name="delegate",
                    arguments={"prompt": "Trigger child provider billing failure.", "model": "test"},
                    run_buffers={},
                    session_buffers={},
                    session_id="delegate_billing_failure",
                    vault_name=vault.name,
                )
            finally:
                delegate_module.create_agent = _patched_create_agent
            billing_tool_result = normalize_tool_result(
                "delegate",
                billing_result,
                vault_path=str(vault),
            )
            self.soft_assert_equal(
                billing_tool_result.metadata.get("status"),
                "failed",
                "Delegate provider failure should return a failed tool result",
            )
            self.soft_assert_equal(
                billing_tool_result.metadata.get("failure_kind"),
                "billing",
                "Delegate provider billing failure should be classified",
            )
            self.soft_assert_equal(
                billing_tool_result.metadata.get("retryable"),
                False,
                "Delegate provider billing failure should be non-retryable without user action",
            )
            self.soft_assert_equal(
                billing_tool_result.metadata.get("http_status"),
                400,
                "Delegate provider failure metadata should include HTTP status",
            )

        finally:
            chat_executor._prepare_agent_config = original_prepare
            delegate_module.create_agent = original_create_agent

        # --- Monty direct tool: delegate with tools ---
        self.create_file(
            vault,
            "AssistantMD/Authoring/delegate_with_tools.md",
            DELEGATE_WITH_TOOLS_WORKFLOW,
        )
        checkpoint = self.event_checkpoint()
        with_tools_result = await self.run_workflow(vault, "delegate_with_tools")
        self.soft_assert_equal(
            with_tools_result.status,
            "completed",
            "Delegate with tools workflow should complete",
        )
        with_tools_events = self.events_since(checkpoint)

        self.assert_event_contains(
            with_tools_events,
            name="authoring_direct_tool_started",
            expected={
                "workflow_id": "DelegateToolVault/delegate_with_tools",
                "tool": "delegate",
            },
        )
        self.assert_event_contains(
            with_tools_events,
            name="delegate_tool_binding_resolved",
            expected={
                "workflow_id": "DelegateToolVault/delegate_with_tools",
                "requested": ["file_ops_safe"],
            },
        )
        self.assert_event_contains(
            with_tools_events,
            name="delegate_completed",
            expected={"workflow_id": "DelegateToolVault/delegate_with_tools"},
        )
        self.assert_event_contains(
            with_tools_events,
            name="authoring_direct_tool_completed",
            expected={
                "workflow_id": "DelegateToolVault/delegate_with_tools",
                "tool": "delegate",
            },
        )

        with_tools_output = vault / "outputs" / "delegate-with-tools-result.md"
        self.soft_assert(
            with_tools_output.exists(),
            "Delegate with tools workflow should write output file",
        )
        if with_tools_output.exists():
            self.soft_assert(
                bool(with_tools_output.read_text(encoding="utf-8").strip()),
                "Delegate with tools output should be non-empty",
            )

        # --- Direct tool result exposes child-run audit metadata for debugging ---
        from core.authoring.helpers.runtime_common import (
            invoke_bound_tool,
            normalize_tool_result,
        )
        from core.authoring.shared.tool_binding import resolve_tool_binding

        audit_binding = resolve_tool_binding(["delegate"], vault_path=str(vault))
        audit_raw_result = await invoke_bound_tool(
            audit_binding.tool_functions[0],
            tool_name="delegate",
            arguments={
                "prompt": "Read notes/content.md and return its text.",
                "tools": ["file_ops_safe"],
                "model": "test",
            },
            run_buffers={},
            session_buffers={},
            session_id="delegate_audit_metadata",
            vault_name=vault.name,
        )
        audit_result = normalize_tool_result(
            "delegate",
            audit_raw_result,
            vault_path=str(vault),
        )
        audit = audit_result.metadata.get("audit")
        self.soft_assert(
            isinstance(audit, dict),
            "Delegate direct tool metadata should include child-run audit details",
        )
        if isinstance(audit, dict):
            self.soft_assert(
                audit.get("tool_call_count", 0) >= 1,
                "Delegate audit should count child tool calls",
            )
            tool_calls = audit.get("tool_calls")
            self.soft_assert(
                isinstance(tool_calls, list) and bool(tool_calls),
                "Delegate audit should include compact child tool call entries",
            )
            if isinstance(tool_calls, list) and tool_calls:
                self.soft_assert_equal(
                    tool_calls[0].get("tool"),
                    "file_ops_safe",
                    "Delegate audit should record child tool names",
                )
                self.soft_assert(
                    "result" in tool_calls[0],
                    "Delegate audit should include compact child tool return values",
                )

        # --- Monty direct tool: delegate a markdown-with-image source path ---
        self.create_file(
            vault,
            "AssistantMD/Authoring/delegate_markdown_image.md",
            DELEGATE_MARKDOWN_IMAGE_WORKFLOW,
        )
        checkpoint = self.event_checkpoint()
        markdown_image_result = await self.run_workflow(vault, "delegate_markdown_image")
        self.soft_assert_equal(
            markdown_image_result.status,
            "completed",
            "Delegate markdown-with-image workflow should complete",
        )
        markdown_image_events = self.events_since(checkpoint)
        self.assert_event_contains(
            markdown_image_events,
            name="delegate_tool_binding_resolved",
            expected={
                "workflow_id": "DelegateToolVault/delegate_markdown_image",
                "requested": ["file_ops_safe"],
            },
        )
        markdown_image_output = vault / "outputs" / "delegate-markdown-image-result.md"
        self.soft_assert(
            markdown_image_output.exists(),
            "Delegate markdown-with-image workflow should write output file",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()


DELEGATE_WITH_TOOLS_WORKFLOW = """---
run_type: workflow
enabled: false
description: Validate delegate with child tool access
---

## Run

```python
result = await delegate(
    prompt="Read notes/content.md and return its text.",
    tools=["file_ops_safe"],
    model="test",
)
await file_ops_safe(
    operation="write",
    path="outputs/delegate-with-tools-result.md",
    content=result.return_value,
)
await finish(status="completed", reason="delegate-with-tools-ok")
```
"""


DELEGATE_MARKDOWN_IMAGE_WORKFLOW = """---
run_type: workflow
enabled: false
description: Validate delegate with markdown containing an embedded image
---

## Run

```python
result = await delegate(
    prompt="Read notes/with-image.md and describe what source was provided.",
    tools=["file_ops_safe"],
    model="test",
)
await file_ops_safe(
    operation="write",
    path="outputs/delegate-markdown-image-result.md",
    content=result.return_value,
)
await finish(status="completed", reason="delegate-markdown-image-ok")
```
"""
