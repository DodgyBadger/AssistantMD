"""
Integration scenario validating shared output-runtime behavior across authoring surfaces.

Covers one string-DSL workflow and one python_steps workflow writing file and
variable outputs after output-target extraction into shared runtime services.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class OutputSharedRuntimeScenario(BaseScenario):
    """Validate output/runtime parity on the shared path."""

    async def test_scenario(self):
        self.set_date("2026-04-04")
        vault = self.create_vault("OutputSharedRuntimeVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/output_shared_runtime_dsl.md",
            OUTPUT_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/output_shared_runtime_sdk.md",
            OUTPUT_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "OutputSharedRuntimeVault/output_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "OutputSharedRuntimeVault/output_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "output_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL output workflow should succeed")
        dsl_events = self.events_since(checkpoint)
        dsl_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "READ_BUFFER"},
        )
        self.soft_assert(
            "--- FILE: variable: dsl_session_buffer ---" in (dsl_prompt or {}).get("data", {}).get("prompt", ""),
            "DSL read step prompt should include session buffer input",
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "output_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK output workflow should succeed")
        sdk_events = self.events_since(checkpoint)
        sdk_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "read_buffer"},
        )
        self.soft_assert(
            "--- FILE: variable: sdk_session_buffer ---" in (sdk_prompt or {}).get("data", {}).get("prompt", ""),
            "SDK read step prompt should include session buffer input",
        )

        dsl_file = vault / "outputs/dsl-target.md"
        self.soft_assert(dsl_file.exists(), "Expected DSL output file to be created")
        if dsl_file.exists():
            dsl_content = dsl_file.read_text(encoding="utf-8")
            self.soft_assert(
                dsl_content.startswith("# DSL 20260404"),
                "DSL output file should include resolved header content",
            )

        dsl_buffer_file = vault / "outputs/dsl-buffer-read.md"
        self.soft_assert(dsl_buffer_file.exists(), "Expected DSL buffer read output file")

        sdk_file = vault / "outputs/sdk-target.md"
        self.soft_assert(sdk_file.exists(), "Expected SDK output file to be created")
        if sdk_file.exists():
            self.soft_assert(sdk_file.stat().st_size > 0, "SDK output file should not be empty")

        sdk_buffer_file = vault / "outputs/sdk-buffer-read.md"
        self.soft_assert(sdk_buffer_file.exists(), "Expected SDK buffer read output file")

        await self.stop_system()
        self.teardown_scenario()


OUTPUT_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime output parity DSL coverage
---

## WRITE_FILE
@model test
@output file: outputs/dsl-target
@write_mode replace
@header DSL {today:YYYYMMDD}

Write DSL file output.

## WRITE_BUFFER
@model test
@output variable: dsl_session_buffer (scope=session)
@write_mode replace

Write DSL session buffer output.

## READ_BUFFER
@model test
@input variable: dsl_session_buffer (scope=session)
@output file: outputs/dsl-buffer-read
@write_mode replace

Summarize the session buffer content.
"""


OUTPUT_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime output parity SDK coverage
---

```python
write_file = Step(
    name="write_file",
    model="test",
    output=File("outputs/sdk-target").replace(),
    prompt="Write SDK file output.",
)

write_buffer = Step(
    name="write_buffer",
    model="test",
    output=Var("sdk_session_buffer", scope="session").replace(),
    prompt="Write SDK session buffer output.",
)

read_buffer = Step(
    name="read_buffer",
    model="test",
    inputs=[Var("sdk_session_buffer", scope="session")],
    output=File("outputs/sdk-buffer-read").replace(),
    prompt="Summarize the session buffer content.",
)

workflow = Workflow(
    steps=[write_file, write_buffer, read_buffer],
)

workflow.run()
```
"""
