"""
Integration scenario validating python_steps selector parity.

Covers reuse of directive-backed `latest` and `pending` selector semantics for
python_steps file inputs, including deterministic ordering and refs-only prompt
assembly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PythonStepsSelectorParityScenario(BaseScenario):
    """Validate selector and pending parity for python_steps file inputs."""

    async def test_scenario(self):
        vault = self.create_vault("PythonStepsSelectorParityVault")
        self.create_file(vault, "timeline/2026-03-01.md", "OLDER_ENTRY")
        self.create_file(vault, "timeline/2026-03-02.md", "LATEST_ENTRY")
        self.create_file(vault, "tasks/task_a.md", "TASK_A")
        self.create_file(vault, "tasks/task_b.md", "TASK_B")
        self.create_file(
            vault,
            "AssistantMD/Workflows/python_steps_selector_parity.md",
            PYTHON_STEPS_SELECTOR_PARITY_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "PythonStepsSelectorParityVault/python_steps_selector_parity"},
        )

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "python_steps_selector_parity")
        self.soft_assert_equal(result.status, "completed", "First python_steps selector run should succeed")
        events = self.events_since(checkpoint)

        latest_prompt = self.assert_event_contains(
            events,
            name="python_step_prompt",
            expected={"step_name": "latest_pick"},
        )
        latest_prompt_text = (latest_prompt or {}).get("data", {}).get("prompt", "")
        self.soft_assert(
            "LATEST_ENTRY" in latest_prompt_text,
            "latest selector should feed the newest timeline file into the prompt",
        )

        pending_prompt = self.assert_event_contains(
            events,
            name="python_step_prompt",
            expected={"step_name": "pending_pick"},
        )
        pending_prompt_text = (pending_prompt or {}).get("data", {}).get("prompt", "")
        self.soft_assert(
            "- tasks/task_a" in pending_prompt_text,
            "pending selector should resolve the first alphanum task path",
        )
        self.soft_assert(
            "TASK_A" not in pending_prompt_text,
            "refs_only input should not inline task content",
        )
        self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={
                "workflow_id": "PythonStepsSelectorParityVault/python_steps_selector_parity",
                "pending_count": 1,
                "pending_paths": ["tasks/task_a"],
            },
        )

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "python_steps_selector_parity")
        self.soft_assert_equal(result.status, "completed", "Second python_steps selector run should succeed")
        events = self.events_since(checkpoint)

        pending_prompt = self.assert_event_contains(
            events,
            name="python_step_prompt",
            expected={"step_name": "pending_pick"},
        )
        pending_prompt_text = (pending_prompt or {}).get("data", {}).get("prompt", "")
        self.soft_assert(
            "- tasks/task_b" in pending_prompt_text,
            "pending selector should advance after successful processing",
        )
        self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={
                "workflow_id": "PythonStepsSelectorParityVault/python_steps_selector_parity",
                "pending_count": 1,
                "pending_paths": ["tasks/task_b"],
            },
        )

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "python_steps_selector_parity")
        self.soft_assert_equal(result.status, "completed", "Third python_steps selector run should succeed")
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={
                "workflow_id": "PythonStepsSelectorParityVault/python_steps_selector_parity",
                "pending_count": 0,
            },
        )

        output_path = vault / "python_steps_selector_result.md"
        self.soft_assert(output_path.exists(), "Expected python_steps_selector_result.md to be created")

        await self.stop_system()
        self.teardown_scenario()


PYTHON_STEPS_SELECTOR_PARITY_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: python_steps selector parity coverage
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
            "tasks/*",
            pending=True,
            limit=1,
            order="alphanum",
            dir="asc",
            refs_only=True,
        )
    ],
    output=File("python_steps_selector_result").replace(),
    prompt="Summarize the selected pending task reference.",
)

workflow = Workflow(
    steps=[latest_pick, pending_pick],
)

workflow.run()
```
"""
