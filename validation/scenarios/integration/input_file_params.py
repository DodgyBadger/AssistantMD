"""
Directive-focused scenario to keep @input-file params stable without heavy runs.

Philosophy:
- Work from a real workflow file so structure stays representative.
- Exercise the directive + prompt composition layer directly (fast, no tools/LLM).
- Cover long-lived behaviors: path-only handling, parentheses in paths, required skip.
"""

import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario
from core.workflow.parser import process_step_content
from workflow_engines.step.workflow import build_final_prompt


class InputFileParamsScenario(BaseScenario):
    """Validate @input-file path-only and required behaviors via prompt composition."""

    async def test_scenario(self):
        vault = self.create_vault("InputFileParamsVault")

        # Seed files referenced by the workflow
        self.create_file(vault, "notes/inline.md", "INLINE_CONTENT")
        self.create_file(vault, "notes/with (parens).md", "PARENS_CONTENT")

        # Seed a representative workflow file (not executed end-to-end here)
        self.create_file(
            vault,
            "AssistantMD/Workflows/input_file_params.md",
            WORKFLOW_CONTENT,
        )

        # Parse step bodies from the workflow file to feed the directive processor
        steps = self._extract_steps(vault / "AssistantMD/Workflows/input_file_params.md")

        # --- paths_only behavior ---
        paths_step = steps["PATHS_ONLY"]
        processed_paths = process_step_content(paths_step, str(vault))
        prompt_paths = build_final_prompt(processed_paths)

        # Inline file content should appear; path-only file should be listed but not inlined
        self.expect_equals(
            "INLINE_CONTENT" in prompt_paths,
            True,
            "Inline file content should be present in prompt",
        )
        self.expect_equals(
            "PARENS_CONTENT" in prompt_paths,
            False,
            "Path-only file content should not be inlined",
        )
        self.expect_equals(
            "- notes/with (parens)" in prompt_paths,
            True,
            "Path-only file should be listed in prompt",
        )

        # --- required skip signal ---
        required_step = steps["REQUIRED_SKIP"]
        processed_required = process_step_content(required_step, str(vault))
        input_result = processed_required.get_directive_value("input_file", [])
        skip_signal = input_result and input_result[0].get("_workflow_signal") == "skip_step"
        self.expect_equals(
            skip_signal,
            True,
            "Required input should signal skip when no files are found",
        )

        self.teardown_scenario()

    def _extract_steps(self, workflow_path: Path) -> Dict[str, str]:
        """Lightweight step extractor: split on '## ' headers after frontmatter."""
        content = workflow_path.read_text()
        # Drop frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            content = parts[2] if len(parts) > 2 else ""

        steps: Dict[str, str] = {}
        current = None
        buffer: list[str] = []
        for line in content.splitlines():
            if line.startswith("## "):
                # Save previous step
                if current:
                    steps[current] = "\n".join(buffer).strip()
                    buffer = []
                current = line[3:].strip()
            else:
                buffer.append(line)
        if current:
            steps[current] = "\n".join(buffer).strip()
        return steps


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
