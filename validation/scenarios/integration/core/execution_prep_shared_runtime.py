"""
Integration scenario validating shared execution-prep behavior across authoring surfaces.

Covers cross-surface parity for run gating and model-none skip behavior after
execution-prep extraction into shared runtime services.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ExecutionPrepSharedRuntimeScenario(BaseScenario):
    """Validate run_on and model-none parity between DSL and python_steps."""

    async def test_scenario(self):
        self.set_date("2026-03-02")
        vault = self.create_vault("ExecutionPrepSharedRuntimeVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/execution_prep_shared_runtime_dsl.md",
            EXECUTION_PREP_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/execution_prep_shared_runtime_sdk.md",
            EXECUTION_PREP_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "ExecutionPrepSharedRuntimeVault/execution_prep_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "ExecutionPrepSharedRuntimeVault/execution_prep_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "execution_prep_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL execution-prep workflow should succeed")
        dsl_events = self.events_since(checkpoint)
        self.assert_event_contains(
            dsl_events,
            name="workflow_step_skipped",
            expected={"step_name": "RUN_ON_NEVER", "reason": "run_on"},
        )
        self.assert_event_contains(
            dsl_events,
            name="workflow_step_skipped",
            expected={"step_name": "MODEL_NONE", "reason": "model_none"},
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "execution_prep_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK execution-prep workflow should succeed")
        sdk_events = self.events_since(checkpoint)
        self.assert_event_contains(
            sdk_events,
            name="python_step_skipped",
            expected={"step_name": "run_on_never", "reason": "run_on"},
        )
        self.assert_event_contains(
            sdk_events,
            name="python_step_skipped",
            expected={"step_name": "model_none", "reason": "model_none"},
        )

        self.soft_assert(
            not (vault / "dsl-run-never.md").exists(),
            "DSL run_on=never step should not write output",
        )
        self.soft_assert(
            not (vault / "dsl-model-none.md").exists(),
            "DSL model=none step should not write output",
        )
        self.soft_assert(
            not (vault / "sdk-run-never.md").exists(),
            "SDK run_on=never step should not write output",
        )
        self.soft_assert(
            not (vault / "sdk-model-none.md").exists(),
            "SDK model=none step should not write output",
        )

        await self.stop_system()
        self.teardown_scenario()


EXECUTION_PREP_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime execution prep DSL coverage
---

## RUN_ON_NEVER
@model test
@run_on never
@output file: dsl-run-never

This step should never run.

## MODEL_NONE
@model none
@output file: dsl-model-none

This step should skip model execution.
"""


EXECUTION_PREP_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime execution prep SDK coverage
---

```python
run_on_never = Step(
    name="run_on_never",
    model="test",
    run_on="never",
    output=File("sdk-run-never").replace(),
    prompt="This step should never run.",
)

model_none = Step(
    name="model_none",
    model="none",
    output=File("sdk-model-none").replace(),
    prompt="This step should skip model execution.",
)

workflow = Workflow(
    steps=[run_on_never, model_none],
)

workflow.run()
```
"""
