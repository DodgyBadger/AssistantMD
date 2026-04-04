"""
Integration scenario validating shared input-runtime behavior across authoring surfaces.

Covers one string-DSL workflow and one python_steps workflow selecting from the
same files with equivalent latest/pending semantics after input extraction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class InputSelectorSharedRuntimeScenario(BaseScenario):
    """Validate selector parity between string DSL and python_steps."""

    async def test_scenario(self):
        vault = self.create_vault("InputSelectorSharedRuntimeVault")
        self.create_file(vault, "timeline/2026-03-01.md", "OLDER_ENTRY")
        self.create_file(vault, "timeline/2026-03-02.md", "LATEST_ENTRY")
        self.create_file(vault, "tasks_dsl/task_a.md", "TASK_A_DSL")
        self.create_file(vault, "tasks_dsl/task_b.md", "TASK_B_DSL")
        self.create_file(vault, "tasks_sdk/task_a.md", "TASK_A_SDK")
        self.create_file(vault, "tasks_sdk/task_b.md", "TASK_B_SDK")
        self.create_file(
            vault,
            "AssistantMD/Workflows/input_selector_shared_runtime_dsl.md",
            SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/input_selector_shared_runtime_sdk.md",
            SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "InputSelectorSharedRuntimeVault/input_selector_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "InputSelectorSharedRuntimeVault/input_selector_shared_runtime_sdk"},
        )

        await self._assert_run(
            vault=vault,
            workflow_name="input_selector_shared_runtime_dsl",
            workflow_id="InputSelectorSharedRuntimeVault/input_selector_shared_runtime_dsl",
            expected_pending_path="tasks_dsl/task_a",
        )
        await self._assert_run(
            vault=vault,
            workflow_name="input_selector_shared_runtime_sdk",
            workflow_id="InputSelectorSharedRuntimeVault/input_selector_shared_runtime_sdk",
            expected_pending_path="tasks_sdk/task_a",
            expected_prompt_step="latest_pick",
        )

        await self._assert_run(
            vault=vault,
            workflow_name="input_selector_shared_runtime_dsl",
            workflow_id="InputSelectorSharedRuntimeVault/input_selector_shared_runtime_dsl",
            expected_pending_path="tasks_dsl/task_b",
        )
        await self._assert_run(
            vault=vault,
            workflow_name="input_selector_shared_runtime_sdk",
            workflow_id="InputSelectorSharedRuntimeVault/input_selector_shared_runtime_sdk",
            expected_pending_path="tasks_sdk/task_b",
            expected_prompt_step="pending_pick",
        )

        await self.stop_system()
        self.teardown_scenario()

    async def _assert_run(
        self,
        *,
        vault,
        workflow_name: str,
        workflow_id: str,
        expected_pending_path: str,
        expected_prompt_step: str | None = None,
    ) -> None:
        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, workflow_name)
        self.soft_assert_equal(result.status, "completed", f"{workflow_name} should succeed")
        events = self.events_since(checkpoint)

        self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={
                "workflow_id": workflow_id,
                "pending_count": 1,
                "pending_paths": [expected_pending_path],
            },
        )
        if expected_prompt_step:
            prompt_event = self.assert_event_contains(
                events,
                name="python_step_prompt",
                expected={"step_name": expected_prompt_step},
            )
            prompt_text = (prompt_event or {}).get("data", {}).get("prompt", "")
            self.soft_assert(
                "LATEST_ENTRY" in prompt_text or expected_pending_path in prompt_text,
                f"{workflow_name} prompt should include selected input content or refs",
            )


SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime selector parity DSL coverage
---

## latest_pick
@model test
@input file: timeline/* (latest, limit=1, order=filename_dt, dir=desc, dt_pattern="(\\d{4}-\\d{2}-\\d{2})", dt_format="YYYY-MM-DD")
@output variable: latest_capture

Summarize the latest timeline entry.

## pending_pick
@model test
@input file: tasks_dsl/* (pending, limit=1, order=alphanum, dir=asc, refs_only)
@output file: shared_runtime_dsl_result

Summarize the selected pending task reference.
"""


SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime selector parity SDK coverage
---

```python
latest_pick = Step(
    name="latest_pick",
    model="test",
    inputs=[
        File(
            "timeline/*",
            latest=True,
            limit=1,
            order="filename_dt",
            dir="desc",
            dt_pattern="(\\\\d{4}-\\\\d{2}-\\\\d{2})",
            dt_format="YYYY-MM-DD",
        )
    ],
    output=Var("latest_capture"),
    prompt="Summarize the latest timeline entry.",
)

pending_pick = Step(
    name="pending_pick",
    model="test",
    inputs=[
        File(
            "tasks_sdk/*",
            pending=True,
            limit=1,
            order="alphanum",
            dir="asc",
            refs_only=True,
        )
    ],
    output=File("shared_runtime_sdk_result").replace(),
    prompt="Summarize the selected pending task reference.",
)

workflow = Workflow(
    steps=[latest_pick, pending_pick],
)

workflow.run()
```
"""
