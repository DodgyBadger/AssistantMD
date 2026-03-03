"""
Deterministic image contract scenario.

Validates direct image @input handling, images=ignore behavior, embedded images,
missing image markers, and prompt assembly signals via validation events.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ImageContractScenario(BaseScenario):
    """Validate multimodal prompt-assembly contract using deterministic model."""

    async def test_scenario(self):
        vault = self.create_vault("ImageInputVault")

        self.create_file(
            vault,
            "AssistantMD/Workflows/image_contract.md",
            IMAGE_CONTRACT_WORKFLOW,
        )

        self.copy_files("validation/templates/files/test_image.jpg", vault, "images")
        self.copy_files(
            "validation/templates/files/test_image.jpg",
            vault,
            "images",
            dest_filename="embedded_image.jpg",
        )
        self.copy_files(
            "validation/templates/files/test_image.jpg",
            vault,
            "images",
            dest_filename="ignored_image.jpg",
        )

        self.create_file(vault, "notes/with_image.md", WITH_IMAGE_MD)
        self.create_file(vault, "notes/missing_image.md", MISSING_IMAGE_MD)

        checkpoint = self.event_checkpoint()
        await self.start_system()

        result = await self.run_workflow(vault, "image_contract")
        assert result.status == "completed", result.error_message

        events = self.events_since(checkpoint)
        step1_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP1"},
        )
        step1_data = step1_event.get("data", {})
        step1_prompt = step1_data.get("prompt", "")
        step1_attached = step1_data.get("attached_image_count", 0)
        step1_warnings = step1_data.get("prompt_warnings", []) or []

        assert "images/test_image.jpg" in step1_prompt
        assert "embedded_image.jpg" in step1_prompt
        assert "ignored_image.jpg" in step1_prompt
        assert "[MISSING IMAGE: images/missing.jpg]" in step1_prompt
        assert step1_attached >= 1
        assert any("Could not resolve embedded image" in item for item in step1_warnings)

        step2_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP2_IGNORE_ONLY"},
        )
        step2_data = step2_event.get("data", {})
        step2_prompt = step2_data.get("prompt", "")
        step2_attached = step2_data.get("attached_image_count", 0)
        assert "images/ignored_image.jpg" in step2_prompt
        assert step2_attached == 0, (
            "images=ignore should suppress image attachment for direct image inputs"
        )

        await self.stop_system()
        self.teardown_scenario()


IMAGE_CONTRACT_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Validate image prompt-assembly contract
---

## STEP1
@model test
@input file: images/test_image.jpg
@input file: images/ignored_image.jpg (images=ignore)
@input file: notes/with_image.md
@input file: notes/missing_image.md
@output variable: image_policy_buffer

Write a short note acknowledging receipt of the inputs.

## STEP2_IGNORE_ONLY
@model test
@input file: images/ignored_image.jpg (images=ignore)
@output variable: ignored_only_buffer

Confirm the ignored image input was processed as reference-only.
"""


WITH_IMAGE_MD = """Here is an embedded image.

![Embedded test image](../images/embedded_image.jpg)

End of note.
"""


MISSING_IMAGE_MD = """Here is a missing embedded image.

![Missing test image](images/missing.jpg)
"""
