"""
Integration scenario validating @input selector error contracts.

Covers breaking migration errors and selector validation failures without
adding production-only validation events.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class InputSelectorValidationScenario(BaseScenario):
    """Validate @input selector mode failure contracts and guidance messages."""

    async def test_scenario(self):
        vault = self.create_vault("InputSelectorValidationVault")

        self.create_file(vault, "tasks/task1.md", "TASK_ONE")
        self.create_file(vault, "tasks/task2.md", "TASK_TWO")
        self.create_file(vault, "timeline/2026-03-01.md", "OLDER_ENTRY")
        self.create_file(vault, "timeline/2026-03-02.md", "LATEST_ENTRY")
        self.create_file(vault, "projects/a/notes.md", "PROJECT_A_NOTES")
        self.create_file(vault, "projects/b/notes.md", "PROJECT_B_NOTES")

        self.create_file(
            vault,
            "AssistantMD/Workflows/input_selector_validation.md",
            INPUT_SELECTOR_VALIDATION_WORKFLOW,
        )

        await self.start_system()

        # Baseline valid selector behavior should still execute successfully.
        ok = await self.run_workflow(vault, "input_selector_validation", step_name="VALID_BASELINE")
        self.soft_assert_equal(ok.status, "completed", "Baseline selector step should succeed")
        no_selector_mods = await self.run_workflow(
            vault,
            "input_selector_validation",
            step_name="NO_SELECTOR_MODIFIERS",
        )
        self.soft_assert_equal(
            no_selector_mods.status,
            "completed",
            "Non-selector order/dir/limit step should succeed",
        )

        await self._assert_step_fails_with(
            vault,
            "LEGACY_PENDING",
            "Legacy '{pending}' syntax is no longer supported",
        )
        await self._assert_step_fails_with(
            vault,
            "LEGACY_LATEST",
            "Legacy '{latest}' syntax is no longer supported",
        )
        await self._assert_step_fails_with(
            vault,
            "SELECTOR_XOR",
            "choose either pending or latest",
        )
        await self._assert_step_fails_with(
            vault,
            "LATEST_ALPHANUM",
            "order 'alphanum' is not supported for latest",
        )
        await self._assert_step_fails_with(
            vault,
            "FILENAME_DT_MISSING_CONFIG",
            "filename_dt ordering requires dt_pattern and dt_format",
        )
        await self._assert_step_fails_with(
            vault,
            "DIRECTORY_ONLY_PATTERN",
            "resolved to directories only",
        )

        await self.stop_system()
        self.teardown_scenario()

    async def _assert_step_fails_with(self, vault, step_name: str, expected_substring: str):
        result = await self.run_workflow(vault, "input_selector_validation", step_name=step_name)
        self.soft_assert_equal(
            result.status,
            "failed",
            f"Step {step_name} should fail",
        )
        self.soft_assert(
            expected_substring in (result.error_message or ""),
            f"Step {step_name} should include expected error text: {expected_substring}",
        )


INPUT_SELECTOR_VALIDATION_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Input selector validation coverage
---

## VALID_BASELINE
@model test
@input file: timeline/* (latest, limit=1)
@output variable: baseline

Baseline selector step should succeed.

## NO_SELECTOR_MODIFIERS
@model test
@input file: timeline/* (order=ctime, dir=desc, limit=1)
@output variable: no_selector_mods

Glob ordering and limit without pending/latest should succeed.

## LEGACY_PENDING
@model test
@input file: tasks/{pending:2}
@output variable: legacy_pending

Legacy pending brace syntax should fail.

## LEGACY_LATEST
@model test
@input file: timeline/{latest}
@output variable: legacy_latest

Legacy latest brace syntax should fail.

## SELECTOR_XOR
@model test
@input file: timeline/* (pending, latest)
@output variable: selector_xor

pending + latest in one directive should fail.

## LATEST_ALPHANUM
@model test
@input file: timeline/* (latest, order=alphanum)
@output variable: latest_alphanum

latest with alphanum ordering should fail.

## FILENAME_DT_MISSING_CONFIG
@model test
@input file: timeline/* (latest, order=filename_dt)
@output variable: missing_dt_config

filename_dt ordering without dt_pattern/dt_format should fail.

## DIRECTORY_ONLY_PATTERN
@model test
@input file: projects/*/ (latest)
@output variable: directory_only

Directory-only file pattern should fail with guidance.
"""
