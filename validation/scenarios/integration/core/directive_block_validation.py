"""
Integration scenario validating fenced directive block parsing contracts.

Covers the optional top-of-step fenced directive block syntax and invalid
mixing with inline directive syntax in the same step.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class DirectiveBlockValidationScenario(BaseScenario):
    """Validate fenced directive block success and failure contracts."""

    async def test_scenario(self):
        vault = self.create_vault("DirectiveBlockValidationVault")

        self.create_file(vault, "notes/plain.md", "PLAIN_BODY")
        self.create_file(
            vault,
            "AssistantMD/Workflows/directive_block_validation.md",
            DIRECTIVE_BLOCK_VALIDATION_WORKFLOW,
        )

        await self.start_system()

        ok = await self.run_workflow(vault, "directive_block_validation", step_name="VALID_FENCED")
        self.soft_assert_equal(ok.status, "completed", "Valid fenced directive step should succeed")

        await self._assert_step_fails_with(
            vault,
            "MIX_FENCED_THEN_INLINE",
            "Cannot mix fenced and inline directive syntax in the same step",
        )
        await self._assert_step_fails_with(
            vault,
            "MIX_INLINE_THEN_FENCED",
            "Cannot mix inline and fenced directive syntax in the same step",
        )

        await self.stop_system()
        self.teardown_scenario()

    async def _assert_step_fails_with(self, vault, step_name: str, expected_substring: str):
        result = await self.run_workflow(
            vault,
            "directive_block_validation",
            step_name=step_name,
            expect_failure=True,
        )
        self.soft_assert_equal(result.status, "failed", f"Step {step_name} should fail")
        self.soft_assert(
            expected_substring in (result.error_message or ""),
            f"Step {step_name} should include expected error text: {expected_substring}",
        )


DIRECTIVE_BLOCK_VALIDATION_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Fenced directive block validation coverage
---

## VALID_FENCED
```
@model test
@input file: notes/plain
@output variable: valid_fenced
```

Valid fenced directive block should succeed.

## MIX_FENCED_THEN_INLINE
```
@model test
@input file: notes/plain
```
@output variable: invalid_after_fence

Mixing fenced then inline directives should fail.

## MIX_INLINE_THEN_FENCED
@model test
```
@input file: notes/plain
@output variable: invalid_after_inline
```

Mixing inline then fenced directives should fail.
"""
