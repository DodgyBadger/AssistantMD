"""
Integration scenario that exercises tool output routing and @input routing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ToolOutputRoutingScenario(BaseScenario):
    """Validate tool output routing + input routing manifests."""

    async def test_scenario(self):
        vault = self.create_vault("ToolRoutingVault")

        # Seed files for @input routing
        self.create_file(vault, "notes/a.md", "Alpha")
        self.create_file(vault, "notes/b.md", "Beta")

        self.create_file(
            vault,
            "AssistantMD/Workflows/tool_output_routing.md",
            WORKFLOW_CONTENT,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()

        result = await self.run_workflow(vault, "tool_output_routing")
        assert result.status == "completed", "Routing workflow should complete"

        events = self.events_since(checkpoint)

        # Input routing: refs_only should route path list
        self.assert_event_contains(
            events,
            name="input_routed",
            expected={
                "destination": "variable: routed_refs",
                "refs_only": True,
                "item_count": 2,
            },
        )

        # Tool routing to buffer and file should emit routing events
        self.assert_event_contains(
            events,
            name="tool_output_routed",
            expected={
                "tool": "file_ops_safe",
                "destination": "variable: tool_buffer",
            },
        )
        self.assert_event_contains(
            events,
            name="tool_output_routed",
            expected={
                "tool": "file_ops_safe",
            },
        )

        # Confirm file output target created by routed tool output
        output_path = vault / "tool-outputs" / "listing.md"
        assert output_path.exists(), "Expected routed file output to be created"
        assert output_path.stat().st_size > 0, "Routed file output is empty"

        await self.stop_system()
        self.teardown_scenario()


WORKFLOW_CONTENT = """---
workflow_engine: step
enabled: false
description: Validation workflow for tool output routing
---

## ROUTE_INPUT_REFS
@model test
@input file:notes/*.md (refs_only=true, output=variable: routed_refs)

Route input references to a buffer variable.

## TOOL_TO_BUFFER
@model gpt-mini
@tools file_ops_safe(output=variable: tool_buffer)
@output file: tool-outputs/tool-to-buffer

Use the safe file operations tool to list the root of the vault.
You must call the tool before responding.

## TOOL_TO_FILE
@model gpt-mini
@tools file_ops_safe(output=file: tool-outputs/listing)
@output file: tool-outputs/tool-to-file

Use the safe file operations tool to list the root of the vault again.
You must call the tool before responding.
"""
