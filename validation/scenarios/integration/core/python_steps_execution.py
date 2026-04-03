"""
Integration scenario validating minimal python_steps execution.

Covers prompt-step execution, variable output, downstream variable input,
and sequential execution through `workflow.run()`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PythonStepsExecutionScenario(BaseScenario):
    """Validate the minimal runnable python_steps subset."""

    async def test_scenario(self):
        vault = self.create_vault("PythonStepsExecutionVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/python_steps_execution.md",
            PYTHON_STEPS_EXECUTION_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PythonStepsExecutionVault/python_steps_execution"},
        )

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "python_steps_execution")
        self.soft_assert_equal(result.status, "completed", "python_steps workflow should execute")
        events = self.events_since(checkpoint)

        self.assert_event_contains(
            events,
            name="python_step_started",
            expected={"workflow_id": "PythonStepsExecutionVault/python_steps_execution", "step_name": "gather"},
        )
        self.assert_event_contains(
            events,
            name="python_step_started",
            expected={"workflow_id": "PythonStepsExecutionVault/python_steps_execution", "step_name": "echo"},
        )
        self.assert_event_contains(
            events,
            name="python_workflow_started",
            expected={"workflow_id": "PythonStepsExecutionVault/python_steps_execution"},
        )
        prompt_event = self.assert_event_contains(
            events,
            name="python_step_prompt",
            expected={"step_name": "echo"},
        )
        prompt_text = (prompt_event or {}).get("data", {}).get("prompt", "")
        self.soft_assert(
            "--- INPUT: variable:gathered ---" in prompt_text,
            "echo step prompt should include gathered variable input",
        )

        output_path = vault / "python_steps_result.md"
        self.soft_assert(output_path.exists(), "Expected python_steps_result.md to be created")
        if output_path.exists():
            self.soft_assert(output_path.stat().st_size > 0, "python_steps_result.md should not be empty")

        await self.stop_system()
        self.teardown_scenario()


PYTHON_STEPS_EXECUTION_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Minimal python_steps execution coverage
---

```python
gather = Step(
    name="gather",
    model="test",
    output=Var("gathered"),
    prompt="Write one short line about workflow execution.",
)

echo = Step(
    name="echo",
    model="test",
    inputs=[Var("gathered")],
    output=File("python_steps_result").replace(),
    prompt="Summarize the gathered line in one sentence.",
)

workflow = Workflow(
    steps=[gather, echo],
)

workflow.run()
```
"""
