"""
Integration scenario validating the date-pattern path matrix across authoring surfaces.

Covers the base shared output-path patterns for both the string DSL and
python_steps using one fan-out step per surface.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PathExpansionMatrixSharedRuntimeScenario(BaseScenario):
    """Validate the shared output date-pattern matrix between DSL and python_steps."""

    async def test_scenario(self):
        self.set_date("2026-03-02")
        vault = self.create_vault("PathExpansionMatrixSharedRuntimeVault")
        self.create_file(vault, "timeline/2026-03-02.md", "TODAY_ENTRY")
        self.create_file(
            vault,
            "AssistantMD/Workflows/path_expansion_matrix_shared_runtime_dsl.md",
            PATH_EXPANSION_MATRIX_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/path_expansion_matrix_shared_runtime_sdk.md",
            PATH_EXPANSION_MATRIX_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PathExpansionMatrixSharedRuntimeVault/path_expansion_matrix_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PathExpansionMatrixSharedRuntimeVault/path_expansion_matrix_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "path_expansion_matrix_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL path-expansion matrix workflow should succeed")
        dsl_events = self.events_since(checkpoint)
        dsl_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "WRITE_MATRIX"},
        )
        self.soft_assert(
            "TODAY_ENTRY" in (dsl_prompt or {}).get("data", {}).get("prompt", ""),
            "DSL matrix prompt should include content from the date-resolved input path",
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "path_expansion_matrix_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK path-expansion matrix workflow should succeed")
        sdk_events = self.events_since(checkpoint)
        sdk_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "write_matrix"},
        )
        self.soft_assert(
            "TODAY_ENTRY" in (sdk_prompt or {}).get("data", {}).get("prompt", ""),
            "SDK matrix prompt should include content from the date-resolved input path",
        )

        expected_outputs = [
            "today/2026-03-02.md",
            "yesterday/2026-03-01.md",
            "tomorrow/2026-03-03.md",
            "this-week/2026-03-01.md",
            "last-week/2026-02-22.md",
            "next-week/2026-03-08.md",
            "this-month/2026-03.md",
            "last-month/2026-02.md",
            "day-name/Monday.md",
            "month-name/March.md",
        ]
        for relative_path in expected_outputs:
            self.soft_assert(
                (vault / "outputs/dsl" / relative_path).exists(),
                f"DSL output path should resolve {relative_path}",
            )
            self.soft_assert(
                (vault / "outputs/sdk" / relative_path).exists(),
                f"SDK output path should resolve {relative_path}",
            )

        await self.stop_system()
        self.teardown_scenario()


PATH_EXPANSION_MATRIX_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime path expansion matrix DSL coverage
week_start_day: sunday
---

## WRITE_MATRIX
@model test
@input file: timeline/{today}
@output file: outputs/dsl/today/{today}
@output file: outputs/dsl/yesterday/{yesterday}
@output file: outputs/dsl/tomorrow/{tomorrow}
@output file: outputs/dsl/this-week/{this-week}
@output file: outputs/dsl/last-week/{last-week}
@output file: outputs/dsl/next-week/{next-week}
@output file: outputs/dsl/this-month/{this-month}
@output file: outputs/dsl/last-month/{last-month}
@output file: outputs/dsl/day-name/{day-name}
@output file: outputs/dsl/month-name/{month-name}
@write_mode replace

Write output-path expansion matrix.
"""


PATH_EXPANSION_MATRIX_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime path expansion matrix SDK coverage
week_start_day: sunday
---

```python
write_matrix = Step(
    name="write_matrix",
    model="test",
    inputs=[File(path.join("timeline", date.today()))],
    outputs=[
        File(path.join("outputs", "sdk", "today", date.today())).replace(),
        File(path.join("outputs", "sdk", "yesterday", date.yesterday())).replace(),
        File(path.join("outputs", "sdk", "tomorrow", date.tomorrow())).replace(),
        File(path.join("outputs", "sdk", "this-week", date.this_week())).replace(),
        File(path.join("outputs", "sdk", "last-week", date.last_week())).replace(),
        File(path.join("outputs", "sdk", "next-week", date.next_week())).replace(),
        File(path.join("outputs", "sdk", "this-month", date.this_month())).replace(),
        File(path.join("outputs", "sdk", "last-month", date.last_month())).replace(),
        File(path.join("outputs", "sdk", "day-name", date.day_name())).replace(),
        File(path.join("outputs", "sdk", "month-name", date.month_name())).replace(),
    ],
    prompt="Write output-path expansion matrix.",
)

workflow = Workflow(
    steps=[write_matrix],
)

workflow.run()
```
"""
