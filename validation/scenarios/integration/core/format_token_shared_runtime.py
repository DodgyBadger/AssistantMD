"""
Integration scenario validating shared format-token path behavior across authoring surfaces.

Covers representative custom format tokens for both the string DSL and
python_steps using the shared date-pattern formatter.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class FormatTokenSharedRuntimeScenario(BaseScenario):
    """Validate representative format-token parity between DSL and python_steps."""

    async def test_scenario(self):
        self.set_date("2026-03-02")
        vault = self.create_vault("FormatTokenSharedRuntimeVault")
        self.create_file(vault, "timeline/2026-03-02.md", "TODAY_ENTRY")
        self.create_file(
            vault,
            "AssistantMD/Workflows/format_token_shared_runtime_dsl.md",
            FORMAT_TOKEN_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/format_token_shared_runtime_sdk.md",
            FORMAT_TOKEN_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "FormatTokenSharedRuntimeVault/format_token_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "FormatTokenSharedRuntimeVault/format_token_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "format_token_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL format-token workflow should succeed")
        dsl_events = self.events_since(checkpoint)
        dsl_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "WRITE_FORMATS"},
        )
        self.soft_assert(
            "TODAY_ENTRY" in (dsl_prompt or {}).get("data", {}).get("prompt", ""),
            "DSL format-token prompt should include content from the date-resolved input path",
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "format_token_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK format-token workflow should succeed")
        sdk_events = self.events_since(checkpoint)
        sdk_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "write_formats"},
        )
        self.soft_assert(
            "TODAY_ENTRY" in (sdk_prompt or {}).get("data", {}).get("prompt", ""),
            "SDK format-token prompt should include content from the date-resolved input path",
        )

        expected_outputs = [
            "ymd-short/260302.md",
            "week-underscored/2026_03_02.md",
            "weekday-short/Mon.md",
            "month-short/Mar.md",
        ]
        for relative_path in expected_outputs:
            self.soft_assert(
                (vault / "outputs/dsl" / relative_path).exists(),
                f"DSL output path should resolve formatted token path {relative_path}",
            )
            self.soft_assert(
                (vault / "outputs/sdk" / relative_path).exists(),
                f"SDK output path should resolve formatted token path {relative_path}",
            )

        await self.stop_system()
        self.teardown_scenario()


FORMAT_TOKEN_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared format token DSL coverage
week_start_day: monday
---

## WRITE_FORMATS
@model test
@input file: timeline/{today}
@output file: outputs/dsl/ymd-short/{today:YYMMDD}
@output file: outputs/dsl/week-underscored/{this-week:YYYY_MM_DD}
@output file: outputs/dsl/weekday-short/{day-name:ddd}
@output file: outputs/dsl/month-short/{month-name:MMM}
@write_mode replace

Write output-path format-token coverage.
"""


FORMAT_TOKEN_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared format token SDK coverage
week_start_day: monday
---

```python
write_formats = Step(
    name="write_formats",
    model="test",
    inputs=[File(path.join("timeline", date.today()))],
    outputs=[
        File(path.join("outputs", "sdk", "ymd-short", date.today(fmt="YYMMDD"))).replace(),
        File(path.join("outputs", "sdk", "week-underscored", date.this_week(fmt="YYYY_MM_DD"))).replace(),
        File(path.join("outputs", "sdk", "weekday-short", date.day_name(fmt="ddd"))).replace(),
        File(path.join("outputs", "sdk", "month-short", date.month_name(fmt="MMM"))).replace(),
    ],
    prompt="Write output-path format-token coverage.",
)

workflow = Workflow(
    steps=[write_formats],
)

workflow.run()
```
"""
