"""
Directive-focused scenario to keep @input params stable without heavy runs.

Philosophy:
- Work from a real workflow file so structure stays representative.
- Exercise the directive + prompt composition layer directly (fast, no tools/LLM).
- Cover long-lived behaviors: path-only handling, parentheses in paths, required skip.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class InputParamsScenario(BaseScenario):
    """Validate @input params via prompt-composition validation artifacts."""

    async def test_scenario(self):
        vault = self.create_vault("InputParamsVault")

        # Seed files referenced by the workflow
        self.create_file(vault, "notes/inline.md", "INLINE_CONTENT")
        self.create_file(vault, "notes/with (parens).md", "PARENS_CONTENT")
        self.create_file(
            vault,
            "notes/with_props.md",
            "---\nstatus: active\nowner: alice\nflag: true\n---\n\nBODY_SHOULD_NOT_APPEAR",
        )
        self.create_file(vault, "notes/no_props.md", "NO_FRONTMATTER_BODY")

        # Seed a representative workflow file (executed end-to-end here)
        self.create_file(
            vault,
            "AssistantMD/Workflows/input_params.md",
            WORKFLOW_CONTENT,
        )

        await self.start_system()

        # Execute workflow to emit validation artifacts for prompt composition
        await self.run_workflow(vault, "input_params")

        events = self.validation_events()

        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "PATHS_ONLY"},
        )
        prompt = prompt_event.get("data", {}).get("prompt", "")
        assert "INLINE_CONTENT" in prompt, (
            "Inline file content should be present in prompt"
        )
        assert "Workflow Guide" in prompt, (
            "Virtual docs file should be resolvable via @input and inlined by default"
        )
        assert "- notes/with (parens)" in prompt, (
            "Path-only file should be listed in prompt"
        )
        assert "PARENS_CONTENT" not in prompt, (
            "Path-only file content should not be inlined"
        )

        properties_prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "PROPERTIES"},
        )
        properties_prompt = properties_prompt_event.get("data", {}).get("prompt", "")
        assert "status: active" in properties_prompt, (
            "properties should include selected key 'status'"
        )
        assert "owner: alice" in properties_prompt, (
            "properties should include selected key 'owner'"
        )
        assert "BODY_SHOULD_NOT_APPEAR" not in properties_prompt, (
            "properties mode should not inline body content"
        )
        assert "- notes/no_props" in properties_prompt, (
            "items without frontmatter should fall back to refs_only paths"
        )

        variable_prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "PROPERTIES_VARIABLE"},
        )
        variable_prompt = variable_prompt_event.get("data", {}).get("prompt", "")
        assert "owner: alice" in variable_prompt, (
            "properties should work for variable inputs sourced from @input routing"
        )
        assert "status: active" not in variable_prompt, (
            "key-filtered properties should exclude unrequested keys"
        )

        self.assert_event_contains(
            events,
            name="workflow_step_skipped",
            expected={"step_name": "REQUIRED_SKIP"},
        )

        await self.stop_system()
        self.teardown_scenario()

WORKFLOW_CONTENT = """---
workflow_engine: step
enabled: false
description: Directive-level validation for input params
---

## PATHS_ONLY
@model test
@input file: notes/inline
@input file: __virtual_docs__/use/workflows
@input file: notes/with (parens) (refs_only)

Summarize the files.

## PROPERTIES
@model test
@input file: notes/with_props (properties=status, owner)
@input file: notes/no_props (properties)

Summarize the properties.

## PROPERTIES_VARIABLE
@model test
@input file: notes/with_props (output=variable: props_src)
@input variable: props_src (properties=owner)

Summarize variable properties.

## REQUIRED_SKIP
@model test
@input file: missing-file (required)

Confirm required input behavior.
"""
