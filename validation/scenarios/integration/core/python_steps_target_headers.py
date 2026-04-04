"""
Integration scenario validating target-level header support for python_steps.

Covers `File(..., header=...)` for both single-target and multi-output writes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PythonStepsTargetHeadersScenario(BaseScenario):
    """Validate target-level header metadata in python_steps."""

    async def test_scenario(self):
        self.set_date("2026-03-02")
        vault = self.create_vault("PythonStepsTargetHeadersVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/python_steps_target_headers.md",
            PYTHON_STEPS_TARGET_HEADERS_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PythonStepsTargetHeadersVault/python_steps_target_headers"},
        )

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "python_steps_target_headers")
        self.soft_assert_equal(result.status, "completed", "python_steps target-header workflow should execute")
        events = self.events_since(checkpoint)

        prompt_event = self.assert_event_contains(
            events,
            name="python_step_prompt",
            expected={"step_name": "fan_out_headers"},
        )
        output_label = (prompt_event or {}).get("data", {}).get("output_target", "")
        self.soft_assert(
            "file:outputs/daily" in output_label and "file:outputs/weekly" in output_label,
            "fan_out_headers step should report both header-bearing file outputs",
        )

        daily_path = vault / "outputs/daily.md"
        weekly_path = vault / "outputs/weekly.md"
        single_path = vault / "outputs/single.md"

        self.soft_assert(daily_path.exists(), "Expected daily header output")
        self.soft_assert(weekly_path.exists(), "Expected weekly header output")
        self.soft_assert(single_path.exists(), "Expected single header output")

        if daily_path.exists():
            self.soft_assert(
                daily_path.read_text(encoding="utf-8").startswith("# Daily 20260302"),
                "Expected resolved day header in daily output",
            )
        if weekly_path.exists():
            self.soft_assert(
                weekly_path.read_text(encoding="utf-8").startswith("# Weekly 2026-03-02"),
                "Expected resolved week header in weekly output",
            )
        if single_path.exists():
            self.soft_assert(
                single_path.read_text(encoding="utf-8").startswith("# Single Monday"),
                "Expected resolved single-target header output",
            )

        await self.stop_system()
        self.teardown_scenario()


PYTHON_STEPS_TARGET_HEADERS_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: python_steps target header coverage
week_start_day: monday
---

```python
fan_out_headers = Step(
    name="fan_out_headers",
    model="test",
    outputs=[
        File("outputs/daily", header="Daily {today:YYYYMMDD}").replace(),
        File("outputs/weekly", header="Weekly {this-week}").replace(),
    ],
    prompt="Write one short line for the header outputs.",
)

single_header = Step(
    name="single_header",
    model="test",
    output=File("outputs/single", header="Single {day-name}").replace(),
    prompt="Write one short line for the single header output.",
)

workflow = Workflow(
    steps=[fan_out_headers, single_header],
)

workflow.run()
```
"""
