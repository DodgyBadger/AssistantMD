"""
Live API tools smoke scenario.

Covers chat-driven workflow_run tool invocation with a real model/provider path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ApiToolsLiveSmokeScenario(BaseScenario):
    """Minimal live smoke coverage for chat tool invocation."""

    async def test_scenario(self):
        vault = self.create_vault("ApiToolsLiveSmokeVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/status_probe.md",
            STATUS_PROBE_WORKFLOW,
        )

        await self.start_system()

        checkpoint = self.event_checkpoint()
        workflow_tool_chat = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                "vault_name": vault.name,
                "prompt": (
                    "Use workflow_run to list workflows, then run workflow "
                    "'status_probe'. You must call the tool before responding."
                ),
                "tools": ["workflow_run"],
                "model": "gpt-mini",
            },
        )
        assert workflow_tool_chat.status_code == 200, "Chat tool invocation succeeds"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="tool_invoked",
            expected={"tool": "workflow_run"},
        )

        await self.stop_system()
        self.teardown_scenario()


STATUS_PROBE_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Validation helper workflow for live tool smoke
---

## STEP1
@output file: logs/{today}
@model test

Summarize the validation run context.
"""
