"""
Integration scenario validating python_steps workflow load contracts.

Covers startup-time discovery for one valid python_steps workflow and one
invalid workflow that should fail during engine-specific parsing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PythonStepsLoadingScenario(BaseScenario):
    """Validate python_steps workflow load success and parse-failure contracts."""

    async def test_scenario(self):
        vault = self.create_vault("PythonStepsLoadingVault")

        self.create_file(
            vault,
            "AssistantMD/Workflows/python_steps_valid.md",
            PYTHON_STEPS_VALID_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/python_steps_invalid.md",
            PYTHON_STEPS_INVALID_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/python_steps_bad_ref.md",
            PYTHON_STEPS_BAD_REF_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        events = self.events_since(checkpoint)

        self.assert_event_contains(
            events,
            name="python_steps_blocks_parsed",
            expected={
                "workflow_id": "PythonStepsLoadingVault/python_steps_valid",
                "step_count": 1,
            },
        )
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "PythonStepsLoadingVault/python_steps_valid"},
        )
        self.assert_event_contains(
            events,
            name="python_steps_compiled",
            expected={
                "workflow_id": "PythonStepsLoadingVault/python_steps_valid",
            },
        )
        self.assert_event_contains(
            events,
            name="python_steps_parse_failed",
            expected={
                "workflow_id": "PythonStepsLoadingVault/python_steps_invalid",
                "section": "Broken Step",
                "phase": "python_syntax",
            },
        )
        self.assert_event_contains(
            events,
            name="workflow_load_failed",
            expected={
                "workflow_name": "python_steps_invalid",
                "vault_identifier": "PythonStepsLoadingVault/python_steps_invalid",
            },
        )
        self.assert_event_contains(
            events,
            name="python_steps_semantic_validation_failed",
            expected={
                "workflow_id": "PythonStepsLoadingVault/python_steps_bad_ref",
                "step_name": "run_root",
            },
        )
        self.assert_event_contains(
            events,
            name="workflow_load_failed",
            expected={
                "workflow_name": "python_steps_bad_ref",
                "vault_identifier": "PythonStepsLoadingVault/python_steps_bad_ref",
            },
        )

        await self.stop_system()
        self.teardown_scenario()


PYTHON_STEPS_VALID_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Valid python_steps workflow for load-time parsing coverage
---

## Notes
This section is documentation only and should be ignored by the python block loader.

```python
first_step = Step(
    name="first_step",
    model="test",
    prompt="hello from python steps",
)

workflow = Workflow(
    steps=[first_step],
)

workflow.run()
```
"""


PYTHON_STEPS_INVALID_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Invalid python_steps workflow for parse-failure coverage
---

```python
broken_step = Step(
    name="broken_step",
    prompt="missing closing paren"
```
"""


PYTHON_STEPS_BAD_REF_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Invalid python_steps workflow for semantic validation coverage
---

```python
gather = Step(
    name="gather",
    model="test",
    prompt="hello",
)

workflow = Workflow(
    steps=[gather, missing_step],
)

workflow.run()
```
"""
