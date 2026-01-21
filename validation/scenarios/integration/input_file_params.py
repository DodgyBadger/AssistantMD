"""
Directive-focused scenario to keep @input-file params stable without heavy runs.

Philosophy:
- Work from a real workflow file so structure stays representative.
- Exercise the directive + prompt composition layer directly (fast, no tools/LLM).
- Cover long-lived behaviors: path-only handling, parentheses in paths, required skip.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class InputFileParamsScenario(BaseScenario):
    """Validate @input-file path-only and required behaviors via validation artifacts."""

    async def test_scenario(self):
        vault = self.create_vault("InputFileParamsVault")
        artifacts_root = self.run_path / "artifacts"

        # Seed files referenced by the workflow
        self.create_file(vault, "notes/inline.md", "INLINE_CONTENT")
        self.create_file(vault, "notes/with (parens).md", "PARENS_CONTENT")

        # Seed a representative workflow file (executed end-to-end here)
        self.create_file(
            vault,
            "AssistantMD/Workflows/input_file_params.md",
            WORKFLOW_CONTENT,
        )

        await self.start_system()

        # Execute workflow to emit validation artifacts for prompt composition
        await self.run_workflow(vault, "input_file_params")

        events = self._load_validation_events(artifacts_root / "validation_events")

        prompt_events = [
            event for event in events
            if event.get("name") == "workflow_step_prompt"
            and event.get("data", {}).get("step_name") == "PATHS_ONLY"
        ]
        self.expect_true(
            len(prompt_events) > 0,
            "Expected workflow_step_prompt event for PATHS_ONLY step",
        )
        prompt = prompt_events[0].get("data", {}).get("prompt", "")
        self.expect_true(
            "INLINE_CONTENT" in prompt,
            "Inline file content should be present in prompt",
        )
        self.expect_true(
            "- notes/with (parens)" in prompt,
            "Path-only file should be listed in prompt",
        )
        self.expect_false(
            "PARENS_CONTENT" in prompt,
            "Path-only file content should not be inlined",
        )

        skip_events = [
            event for event in events
            if event.get("name") == "workflow_step_skipped"
            and event.get("data", {}).get("step_name") == "REQUIRED_SKIP"
        ]
        self.expect_true(
            len(skip_events) > 0,
            "Expected workflow_step_skipped event for REQUIRED_SKIP step",
        )

        await self.stop_system()
        self.teardown_scenario()

    def _load_validation_events(self, events_dir: Path) -> list[dict]:
        """Load validation events from per-event YAML files."""
        events = []
        if not events_dir.exists():
            return events

        for path in sorted(events_dir.glob("*.yaml")):
            events.append(self.load_yaml(path) or {})

        return events

WORKFLOW_CONTENT = """---
workflow_engine: step
enabled: false
description: Directive-level validation for input-file params
---

## PATHS_ONLY
@model test
@input-file notes/inline
@input-file notes/with (parens) (paths_only)

Summarize the files.

## REQUIRED_SKIP
@model test
@input-file missing-file (required)

Confirm required input behavior.
"""
