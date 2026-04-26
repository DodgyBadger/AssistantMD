"""
Integration scenario for the delegate tool.

Validates delegate as both an LLM-facing chat tool (via patched executor)
and as a Monty direct tool (via workflow runs). Asserts on stable validation
events at decision boundaries and on final output artifacts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.constants import (
    DELEGATE_DEFAULT_MAX_TOOL_CALLS,
    DELEGATE_DEFAULT_TIMEOUT_SECONDS,
)
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
                        "tools": ["file_ops_safe", "delegate", "code_execution_local"],
                    }
                if case == "child_tools":
                    return {
                        "prompt": "List available notes.",
                        "model": "test",
                        "tools": ["file_ops_safe"],
                    }
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
        try:
            # --- Basic: delegate fires and completes ---
            checkpoint = self.event_checkpoint()
            basic = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Run a basic delegate call.",
                    "session_id": "delegate_basic",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert basic.status_code == 200, "Basic delegate call should succeed"
            basic_events = self.events_since(checkpoint)

            self.assert_event_contains(
                basic_events,
                name="delegate_started",
                expected={
                    "workflow_id": "delegate_basic",
                    "model": "test",
                    "max_tool_calls": DELEGATE_DEFAULT_MAX_TOOL_CALLS,
                    "timeout_seconds": DELEGATE_DEFAULT_TIMEOUT_SECONDS,
                },
            )
            self.assert_event_contains(
                basic_events,
                name="delegate_completed",
                expected={
                    "workflow_id": "delegate_basic",
                    "model": "test",
                    "max_tool_calls": DELEGATE_DEFAULT_MAX_TOOL_CALLS,
                    "timeout_seconds": DELEGATE_DEFAULT_TIMEOUT_SECONDS,
                },
            )
            self.soft_assert(
                "failed:" not in basic.json()["response"].lower(),
                "Basic delegate call should not produce a Monty failure response",
            )

            # --- Forbidden tool stripping: delegate and code_execution_local removed ---
            current_case["name"] = "forbidden_stripping"
            checkpoint = self.event_checkpoint()
            stripping = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Test forbidden tool stripping.",
                    "session_id": "delegate_forbidden_stripping",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert stripping.status_code == 200, "Forbidden tool stripping call should succeed"
            stripping_events = self.events_since(checkpoint)

            self.assert_event_contains(
                stripping_events,
                name="delegate_started",
                expected={
                    "workflow_id": "delegate_forbidden_stripping",
                    "tool_names": ["file_ops_safe"],
                    "stripped_tools": ["code_execution_local", "delegate"],
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
            child_tools = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Test delegate with child tools.",
                    "session_id": "delegate_child_tools",
                    "tools": ["delegate"],
                    "model": "test",
                },
            )
            assert child_tools.status_code == 200, "Delegate with child tools should succeed"
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

        finally:
            chat_executor._prepare_agent_config = original_prepare

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
    content=result.output,
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
    content=result.output,
)
await finish(status="completed", reason="delegate-markdown-image-ok")
```
"""
