"""
Integration scenario validating richer python_steps output shapes.

Covers `outputs=[...]`, top-level output target constants, and numbered `new()`
write mode for both file and variable targets.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PythonStepsOutputShapesScenario(BaseScenario):
    """Validate python_steps multi-output and new-mode authoring."""

    async def test_scenario(self):
        vault = self.create_vault("PythonStepsOutputShapesVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/python_steps_output_shapes.md",
            PYTHON_STEPS_OUTPUT_SHAPES_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PythonStepsOutputShapesVault/python_steps_output_shapes"},
        )

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "python_steps_output_shapes")
        self.soft_assert_equal(result.status, "completed", "python_steps output-shapes workflow should execute")
        events = self.events_since(checkpoint)

        prompt_event = self.assert_event_contains(
            events,
            name="python_step_prompt",
            expected={"step_name": "fan_out"},
        )
        output_label = (prompt_event or {}).get("data", {}).get("output_target", "")
        self.soft_assert(
            "file:outputs/multi-a" in output_label and "file:outputs/multi-b" in output_label and "variable:fan_buffer" in output_label,
            "fan_out step should report all output labels",
        )

        self.soft_assert((vault / "outputs/multi-a.md").exists(), "Expected first multi-output file")
        self.soft_assert((vault / "outputs/multi-b.md").exists(), "Expected second multi-output file")

        numbered_file = vault / "outputs/numbered_000.md"
        self.soft_assert(numbered_file.exists(), "Expected numbered file from File(...).new()")
        if numbered_file.exists():
            self.soft_assert(numbered_file.stat().st_size > 0, "Numbered file should not be empty")

        read_prompt = self.assert_event_contains(
            events,
            name="python_step_prompt",
            expected={"step_name": "read_numbered_buffer"},
        )
        read_prompt_text = (read_prompt or {}).get("data", {}).get("prompt", "")
        self.soft_assert(
            "--- FILE: variable: numbered_buffer_000 ---" in read_prompt_text,
            "Var(...).new() should create a numbered buffer visible to downstream input",
        )

        await self.stop_system()
        self.teardown_scenario()


PYTHON_STEPS_OUTPUT_SHAPES_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: python_steps output shape coverage
---

```python
FAN_OUTPUTS = [
    File("outputs/multi-a").replace(),
    File("outputs/multi-b").replace(),
    Var("fan_buffer").replace(),
]

fan_out = Step(
    name="fan_out",
    model="test",
    outputs=FAN_OUTPUTS,
    prompt="Write one short line for all outputs.",
)

numbered_outputs = Step(
    name="numbered_outputs",
    model="test",
    outputs=[
        File("outputs/numbered").new(),
        Var("numbered_buffer").new(),
    ],
    prompt="Write one short numbered entry.",
)

read_numbered_buffer = Step(
    name="read_numbered_buffer",
    model="test",
    inputs=[Var("numbered_buffer_000")],
    output=File("outputs/numbered-buffer-read").replace(),
    prompt="Summarize the numbered buffer entry.",
)

workflow = Workflow(
    steps=[fan_out, numbered_outputs, read_numbered_buffer],
)

workflow.run()
```
"""
