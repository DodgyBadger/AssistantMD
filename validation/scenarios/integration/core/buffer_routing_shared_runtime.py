"""
Integration scenario validating shared buffer and routing behavior across authoring surfaces.

Covers session-scoped variable reads/writes, routed input to variables, and
numbered routed-buffer outputs via write_mode=new for both DSL and python_steps.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class BufferRoutingSharedRuntimeScenario(BaseScenario):
    """Validate buffer and routing parity between string DSL and python_steps."""

    async def test_scenario(self):
        vault = self.create_vault("BufferRoutingSharedRuntimeVault")
        self.create_file(vault, "notes/plain.md", "PLAIN_BODY")
        self.create_file(vault, "batch/a.md", "BATCH_A")
        self.create_file(vault, "batch/b.md", "BATCH_B")
        self.create_file(
            vault,
            "AssistantMD/Workflows/buffer_routing_shared_runtime_dsl.md",
            BUFFER_ROUTING_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/buffer_routing_shared_runtime_sdk.md",
            BUFFER_ROUTING_SHARED_RUNTIME_SDK_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "BufferRoutingSharedRuntimeVault/buffer_routing_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "BufferRoutingSharedRuntimeVault/buffer_routing_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "buffer_routing_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL buffer/routing workflow should succeed")
        dsl_events = self.events_since(checkpoint)

        self.assert_event_contains(
            dsl_events,
            name="input_routed",
            expected={"destination": "variable: routed_note", "refs_only": False, "item_count": 1},
        )
        dsl_session_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "SESSION_READ"},
        )
        self.soft_assert(
            "--- FILE: variable: shared_session ---" in (dsl_session_prompt or {}).get("data", {}).get("prompt", ""),
            "DSL session-scoped variable should be readable downstream",
        )
        dsl_routed_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "ROUTED_READ"},
        )
        self.soft_assert(
            "PLAIN_BODY" in (dsl_routed_prompt or {}).get("data", {}).get("prompt", ""),
            "DSL routed variable should feed downstream input content",
        )
        dsl_numbered_prompt = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "READ_NUMBERED"},
        )
        self.soft_assert(
            "--- FILE: variable: routed_batch_000 ---" in (dsl_numbered_prompt or {}).get("data", {}).get("prompt", ""),
            "DSL write_mode=new routing should create numbered variables",
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "buffer_routing_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK buffer/routing workflow should succeed")
        sdk_events = self.events_since(checkpoint)

        self.assert_event_contains(
            sdk_events,
            name="input_routed",
            expected={"destination": "variable: routed_note", "refs_only": False, "item_count": 1},
        )
        sdk_session_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "session_read"},
        )
        self.soft_assert(
            "--- FILE: variable: shared_session ---" in (sdk_session_prompt or {}).get("data", {}).get("prompt", ""),
            "SDK session-scoped variable should be readable downstream",
        )
        sdk_routed_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "routed_read"},
        )
        self.soft_assert(
            "PLAIN_BODY" in (sdk_routed_prompt or {}).get("data", {}).get("prompt", ""),
            "SDK routed variable should feed downstream input content",
        )
        sdk_numbered_prompt = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "read_numbered"},
        )
        self.soft_assert(
            "--- FILE: variable: routed_batch_000 ---" in (sdk_numbered_prompt or {}).get("data", {}).get("prompt", ""),
            "SDK write_mode=new routing should create numbered variables",
        )

        await self.stop_system()
        self.teardown_scenario()


BUFFER_ROUTING_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime buffer/routing parity DSL coverage
---

## SESSION_WRITE
@model test
@output variable: shared_session (scope=session)

Write a session buffer.

## SESSION_READ
@model test
@input variable: shared_session (scope=session)
@output file: outputs/dsl-session-read

Read the session buffer.

## ROUTED_READ
@model test
@input file: notes/plain (output=variable: routed_note, write_mode=replace)
@input variable: routed_note
@output file: outputs/dsl-routed-read

Read content from a routed variable.

## ROUTE_NEW
@model none
@input file: batch/* (output=variable: routed_batch, write_mode=new)

Create numbered routed variables.

## READ_NUMBERED
@model test
@input variable: routed_batch_000
@output file: outputs/dsl-numbered-read

Read the first numbered routed variable.
"""


BUFFER_ROUTING_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime buffer/routing parity SDK coverage
---

```python
session_write = Step(
    name="session_write",
    model="test",
    output=Var("shared_session", scope="session").replace(),
    prompt="Write a session buffer.",
)

session_read = Step(
    name="session_read",
    model="test",
    inputs=[Var("shared_session", scope="session")],
    output=File("outputs/sdk-session-read").replace(),
    prompt="Read the session buffer.",
)

routed_read = Step(
    name="routed_read",
    model="test",
    inputs=[
        File("notes/plain", output="variable: routed_note", write_mode="replace"),
        Var("routed_note"),
    ],
    output=File("outputs/sdk-routed-read").replace(),
    prompt="Read content from a routed variable.",
)

route_new = Step(
    name="route_new",
    model="none",
    inputs=[
        File("batch/*", output="variable: routed_batch", write_mode="new"),
    ],
    prompt="Create numbered routed variables.",
)

read_numbered = Step(
    name="read_numbered",
    model="test",
    inputs=[Var("routed_batch_000")],
    output=File("outputs/sdk-numbered-read").replace(),
    prompt="Read the first numbered routed variable.",
)

workflow = Workflow(
    steps=[session_write, session_read, routed_read, route_new, read_numbered],
)

workflow.run()
```
"""
