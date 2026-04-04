"""
Integration scenario validating shared tool-binding behavior across authoring surfaces.

Covers one string-DSL workflow and one python_steps workflow resolving the same
tool set through the extracted shared tool-binding runtime.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ToolsSharedRuntimeScenario(BaseScenario):
    """Validate tool-binding parity between DSL and python_steps."""

    async def test_scenario(self):
        vault = self.create_vault("ToolsSharedRuntimeVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/tools_shared_runtime_dsl.md",
            TOOLS_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/tools_shared_runtime_sdk.md",
            TOOLS_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "ToolsSharedRuntimeVault/tools_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "ToolsSharedRuntimeVault/tools_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "tools_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL tools workflow should succeed")
        dsl_events = self.events_since(checkpoint)
        dsl_tools_event = self.assert_event_contains(
            dsl_events,
            name="workflow_step_tools",
            expected={"step_name": "TOOLS_DSL"},
        )
        self.soft_assert(
            "internal_api" in (dsl_tools_event or {}).get("data", {}).get("tool_names", []),
            "DSL tools binding should include internal_api",
        )
        self.assert_event_contains(
            dsl_events,
            name="workflow_step_skipped",
            expected={"step_name": "TOOLS_DSL", "reason": "model_none"},
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "tools_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK tools workflow should succeed")
        sdk_events = self.events_since(checkpoint)
        sdk_tools_event = self.assert_event_contains(
            sdk_events,
            name="python_step_tools",
            expected={"step_name": "tools_sdk"},
        )
        self.soft_assert(
            "internal_api" in (sdk_tools_event or {}).get("data", {}).get("tool_names", []),
            "SDK tools binding should include internal_api",
        )
        self.assert_event_contains(
            sdk_events,
            name="python_step_skipped",
            expected={"step_name": "tools_sdk", "reason": "model_none"},
        )

        await self.stop_system()
        self.teardown_scenario()


TOOLS_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime tool parity DSL coverage
---

## TOOLS_DSL
@model none
@tools internal_api

Write a short line about DSL tool binding.
"""


TOOLS_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime tool parity SDK coverage
---

```python
tools_sdk = Step(
    name="tools_sdk",
    model="none",
    tools=["internal_api"],
    prompt="Write a short line about SDK tool binding.",
)

workflow = Workflow(
    steps=[tools_sdk],
)

workflow.run()
```
"""
