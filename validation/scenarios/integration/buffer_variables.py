"""
Integration scenario that exercises buffer variable I/O via workflow steps.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class BufferVariablesScenario(BaseScenario):
    """Validate buffer read/write/append/replace and required handling."""

    async def test_scenario(self):
        vault = self.create_vault("BufferVariablesVault")

        self.create_file(
            vault,
            "AssistantMD/Workflows/buffer_variables.md",
            WORKFLOW_CONTENT,
        )

        await self.start_system()

        result = await self.run_workflow(vault, "buffer_variables")
        assert result.status == "completed", "Buffer workflow should complete"

        events = self.validation_events()

        # Step 2: read initial buffer
        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "READ_BUFFER"},
        )
        prompt = prompt_event.get("data", {}).get("prompt", "")
        assert "--- FILE: variable:buffer_main ---" in prompt
        assert "success (no tool calls)" in prompt

        # Step 4: read after append (expect two occurrences)
        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "READ_AFTER_APPEND"},
        )
        prompt = prompt_event.get("data", {}).get("prompt", "")
        assert prompt.count("success (no tool calls)") == 2

        # Step 6: read after replace (expect one occurrence)
        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "READ_AFTER_REPLACE"},
        )
        prompt = prompt_event.get("data", {}).get("prompt", "")
        assert prompt.count("success (no tool calls)") == 1

        # Step 7: refs-only should include path but not content
        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "PATHS_ONLY"},
        )
        prompt = prompt_event.get("data", {}).get("prompt", "")
        assert "- variable:buffer_main" in prompt
        assert "success (no tool calls)" not in prompt

        # Step 8: required missing buffer should skip
        self.assert_event_contains(
            events,
            name="workflow_step_skipped",
            expected={"step_name": "REQUIRED_MISSING"},
        )

        await self.stop_system()
        self.teardown_scenario()


WORKFLOW_CONTENT = """---
workflow_engine: step
enabled: false
description: Validation workflow for buffer variables
---

## WRITE_BUFFER
@model test
@output variable:buffer_main

Write buffer seed.

## READ_BUFFER
@model test
@input variable:buffer_main

Read buffer content.

## APPEND_BUFFER
@model test
@input variable:buffer_main
@output variable:buffer_main
@write-mode append

Append another entry.

## READ_AFTER_APPEND
@model test
@input variable:buffer_main

Read appended content.

## REPLACE_BUFFER
@model test
@output variable:buffer_main
@write-mode replace

Replace content.

## READ_AFTER_REPLACE
@model test
@input variable:buffer_main

Read replaced content.

## PATHS_ONLY
@model test
@input variable:buffer_main (refs_only=true)

Paths only check.

## REQUIRED_MISSING
@model test
@input variable:missing_buffer (required)

Should skip.
"""
