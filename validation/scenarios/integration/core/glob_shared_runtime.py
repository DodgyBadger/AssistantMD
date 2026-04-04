"""
Integration scenario validating shared glob/path input behavior across authoring surfaces.

Covers plain glob expansion plus a path containing parentheses in refs-only mode
for both the string DSL and python_steps.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class GlobSharedRuntimeScenario(BaseScenario):
    """Validate shared glob and special-path handling between DSL and python_steps."""

    async def test_scenario(self):
        vault = self.create_vault("GlobSharedRuntimeVault")
        self.create_file(vault, "batch/alpha.md", "ALPHA_BODY")
        self.create_file(vault, "batch/beta.md", "BETA_BODY")
        self.create_file(vault, "refs/with (parens).md", "PARENS_BODY")
        self.create_file(
            vault,
            "AssistantMD/Workflows/glob_shared_runtime_dsl.md",
            GLOB_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/glob_shared_runtime_sdk.md",
            GLOB_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "GlobSharedRuntimeVault/glob_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "GlobSharedRuntimeVault/glob_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "glob_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL glob workflow should succeed")
        dsl_events = self.events_since(checkpoint)
        dsl_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "READ_GLOB"},
        )
        dsl_prompt_text = (dsl_prompt or {}).get("data", {}).get("prompt", "")
        self.soft_assert("ALPHA_BODY" in dsl_prompt_text, "DSL glob prompt should include alpha content")
        self.soft_assert("BETA_BODY" in dsl_prompt_text, "DSL glob prompt should include beta content")
        self.soft_assert("- refs/with (parens)" in dsl_prompt_text, "DSL refs-only prompt should include parentheses path")
        self.soft_assert("PARENS_BODY" not in dsl_prompt_text, "DSL refs-only path should not inline content")

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "glob_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK glob workflow should succeed")
        sdk_events = self.events_since(checkpoint)
        sdk_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "read_glob"},
        )
        sdk_prompt_text = (sdk_prompt or {}).get("data", {}).get("prompt", "")
        self.soft_assert("ALPHA_BODY" in sdk_prompt_text, "SDK glob prompt should include alpha content")
        self.soft_assert("BETA_BODY" in sdk_prompt_text, "SDK glob prompt should include beta content")
        self.soft_assert("- refs/with (parens)" in sdk_prompt_text, "SDK refs-only prompt should include parentheses path")
        self.soft_assert("PARENS_BODY" not in sdk_prompt_text, "SDK refs-only path should not inline content")

        await self.stop_system()
        self.teardown_scenario()


GLOB_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared glob runtime DSL coverage
---

## READ_GLOB
@model test
@input file: batch/*
@input file: refs/with (parens) (refs_only)
@output file: outputs/dsl-glob
@write_mode replace

Read glob and special refs-only path input.
"""


GLOB_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared glob runtime SDK coverage
---

```python
read_glob = Step(
    name="read_glob",
    model="test",
        inputs=[
        File("batch/*"),
        File("refs/with (parens)", refs_only=True),
    ],
    output=File("outputs/sdk-glob").replace(),
    prompt="Read glob and special refs-only path input.",
)

workflow = Workflow(
    steps=[read_glob],
)

workflow.run()
```
"""
