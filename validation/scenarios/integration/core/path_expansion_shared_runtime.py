"""
Integration scenario validating shared path-expansion behavior across authoring surfaces.

Covers file input and output date-pattern expansion for both the string DSL and
python_steps after removing the SDK-local path formatting path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PathExpansionSharedRuntimeScenario(BaseScenario):
    """Validate date-pattern path expansion parity between DSL and python_steps."""

    async def test_scenario(self):
        self.set_date("2026-03-02")
        vault = self.create_vault("PathExpansionSharedRuntimeVault")
        self.create_file(vault, "timeline/2026-03-02.md", "TODAY_ENTRY")
        self.create_file(
            vault,
            "AssistantMD/Workflows/path_expansion_shared_runtime_dsl.md",
            PATH_EXPANSION_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/path_expansion_shared_runtime_sdk.md",
            PATH_EXPANSION_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PathExpansionSharedRuntimeVault/path_expansion_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PathExpansionSharedRuntimeVault/path_expansion_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "path_expansion_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL path-expansion workflow should succeed")
        dsl_events = self.events_since(checkpoint)
        dsl_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "WRITE_WEEK"},
        )
        self.soft_assert(
            "TODAY_ENTRY" in (dsl_prompt or {}).get("data", {}).get("prompt", ""),
            "DSL prompt should include content from the date-resolved input path",
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "path_expansion_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK path-expansion workflow should succeed")
        sdk_events = self.events_since(checkpoint)
        sdk_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "write_week"},
        )
        self.soft_assert(
            "TODAY_ENTRY" in (sdk_prompt or {}).get("data", {}).get("prompt", ""),
            "SDK prompt should include content from the date-resolved input path",
        )

        self.soft_assert(
            (vault / "outputs/dsl-week/2026-03-01.md").exists(),
            "DSL output path should resolve {this-week} using week_start_day=sunday",
        )
        self.soft_assert(
            (vault / "outputs/dsl-day/20260302.md").exists(),
            "DSL output path should resolve formatted {today:YYYYMMDD}",
        )
        self.soft_assert(
            (vault / "outputs/sdk-week/2026-03-01.md").exists(),
            "SDK output path should resolve {this-week} using shared runtime behavior",
        )
        self.soft_assert(
            (vault / "outputs/sdk-day/20260302.md").exists(),
            "SDK output path should resolve formatted {today:YYYYMMDD}",
        )

        await self.stop_system()
        self.teardown_scenario()


PATH_EXPANSION_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime path expansion DSL coverage
week_start_day: sunday
---

## WRITE_WEEK
@model test
@input file: timeline/{today}
@output file: outputs/dsl-week/{this-week}
@write_mode replace

Write weekly expansion output.

## WRITE_DAY
@model test
@input file: timeline/{today}
@output file: outputs/dsl-day/{today:YYYYMMDD}
@write_mode replace

Write day expansion output.
"""


PATH_EXPANSION_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime path expansion SDK coverage
week_start_day: sunday
---

```python
write_week = Step(
    name="write_week",
    model="test",
    inputs=[File(path.join("timeline", date.today()))],
    output=File(path.join("outputs", "sdk-week", date.this_week())).replace(),
    prompt="Write weekly expansion output.",
)

write_day = Step(
    name="write_day",
    model="test",
    inputs=[File(path.join("timeline", date.today()))],
    output=File(path.join("outputs", "sdk-day", date.today(fmt="YYYYMMDD"))).replace(),
    prompt="Write day expansion output.",
)

workflow = Workflow(
    steps=[write_week, write_day],
)

workflow.run()
```
"""
