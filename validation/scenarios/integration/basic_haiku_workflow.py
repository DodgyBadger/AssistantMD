"""
Basic haiku workflow happy-path scenario.

Runs a real image+text workflow end-to-end with a live model to provide
human-reviewable artifacts.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# No more path isolation monkey patches needed! CoreServices handles clean dependency injection.

from validation.core.base_scenario import BaseScenario


class BasicHaikuWorkflowScenario(BaseScenario):
    """Golden-path workflow execution with multimodal input and file outputs."""

    async def test_scenario(self):
        """Execute complete end-to-end workflow: system startup → workflow execution."""

        # === SETUP ===
        vault = self.create_vault("HaikuVault")

        # Create simple single-step workflow
        self.create_file(vault, "AssistantMD/Workflows/haiku_writer.md", HAIKU_WRITER_WORKFLOW)
        self.create_file(
            vault,
            "AssistantMD/Workflows/haiku_writer_monty.md",
            HAIKU_WRITER_MONTY_WORKFLOW,
        )
        self.copy_files("validation/templates/files/test_image.jpg", vault, "images")
        self.create_file(vault, "notes/haiku_seed.md", HAIKU_SEED_NOTE)

        # === SYSTEM STARTUP VALIDATION ===
        # Test real system startup with vault discovery and job scheduling
        checkpoint = self.event_checkpoint()
        await self.start_system()

        # Validate system startup completed correctly
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "HaikuVault/haiku_writer"},
        )
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "HaikuVault/haiku_writer_monty"},
        )
        job_event = self.assert_event_contains(
            events,
            name="job_synced",
            expected={"job_id": "HaikuVault__haiku_writer", "action": "created"},
        )
        trigger = str(job_event.get("data", {}).get("trigger", "")).lower()
        assert "cron" in trigger, "Expected cron trigger"
        monty_job_event = self.assert_event_contains(
            events,
            name="job_synced",
            expected={"job_id": "HaikuVault__haiku_writer_monty", "action": "created"},
        )
        monty_trigger = str(monty_job_event.get("data", {}).get("trigger", "")).lower()
        assert "cron" in monty_trigger, "Expected cron trigger for monty workflow"

        # === SCHEDULED WORKFLOW EXECUTION ===
        # Set a known date for predictable output file naming
        self.set_date("2025-01-15")  # Wednesday

        # Trigger the scheduled job and wait for completion
        checkpoint = self.event_checkpoint()
        assert await self.trigger_job(vault, "haiku_writer"), (
            "Job should execute when triggered"
        )
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="job_executed",
            expected={"job_id": "HaikuVault__haiku_writer"},
        )
        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP2"},
        )
        prompt = prompt_event.get("data", {}).get("prompt", "")
        assert "--- FILE: variable: haiku_buffer ---" in prompt

        # Check output file was created with content
        output_path = vault / "2025-01-15.md"
        assert output_path.exists(), "Expected 2025-01-15.md to be created"
        assert output_path.stat().st_size > 0, "Output file is empty"

        # === MONTY WORKFLOW EXECUTION ===
        checkpoint = self.event_checkpoint()
        assert await self.trigger_job(vault, "haiku_writer_monty"), (
            "Monty job should execute when triggered"
        )
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="job_executed",
            expected={"job_id": "HaikuVault__haiku_writer_monty"},
        )
        self.assert_event_contains(
            events,
            name="authoring_output_written",
            expected={"workflow_id": "HaikuVault/haiku_writer_monty"},
        )

        monty_output_path = vault / "haiku-monty-2025-01-15.md"
        assert monty_output_path.exists(), "Expected haiku-monty-2025-01-15.md to be created"
        assert monty_output_path.stat().st_size > 0, "Monty output file is empty"

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

HAIKU_WRITER_WORKFLOW = """---
schedule: cron: 0 9 * * *
workflow_engine: step
enabled: true
description: Simple haiku writing workflow
---

## STEP1
@input file: images/test_image.jpg
@model gpt-mini
@output file: {today}
@header My new haiku - {today}
@output variable: haiku_buffer

Write a beautiful haiku about the image. Format it nicely with proper line breaks.

## STEP2
@model gpt-mini
@input variable: haiku_buffer
@output file: {today}
@write_mode append
@header Haiku critique

Write a short critique about the above haiku and suggest ways to improve it. Keep it concise and constructive.
"""


HAIKU_WRITER_MONTY_WORKFLOW = """---
schedule: cron: 0 10 * * *
workflow_engine: monty
enabled: true
description: Monty haiku writing workflow
authoring.capabilities: [retrieve, generate, output]
authoring.retrieve.file: [notes/haiku_seed.md]
authoring.output.file: [haiku-monty-*.md]
---

## Run

```python
source = await retrieve(type="file", ref="notes/haiku_seed.md")
note_content = source.items[0].content

draft = await generate(
    prompt=(
        "Write a three-line haiku inspired by this note. Preserve the imagery.\\n\\n"
        + note_content
    ),
    instructions="Write only the haiku with proper line breaks.",
    model="gpt-mini",
)

await output(
    type="file",
    ref=f"haiku-monty-{date.today()}",
    data=draft.output,
)
```
"""


HAIKU_SEED_NOTE = """Morning frost settles over the fence.
The garden is quiet except for a single bird call.
Sunlight is just starting to reach the grass.
"""
