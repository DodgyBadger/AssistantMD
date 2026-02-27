"""
Image input policy scenario.

Validates direct image @input handling, images=ignore behavior, embedded images,
and missing image markers via workflow prompt validation events.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ImageInputPolicyScenario(BaseScenario):
    """Validate image @input prompt assembly behaviors."""

    async def test_scenario(self):
        vault = self.create_vault("ImageInputVault")

        self.create_file(
            vault,
            "AssistantMD/Workflows/image_input_policy.md",
            IMAGE_INPUT_POLICY_WORKFLOW,
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

        result = await self.run_workflow(vault, "image_input_policy")
        assert result.status == "completed", result.error_message

        events = self.events_since(checkpoint)
        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP1"},
        )
        prompt_data = prompt_event.get("data", {})
        prompt = prompt_data.get("prompt", "")
        attached_count = prompt_data.get("attached_image_count", 0)
        warnings = prompt_data.get("prompt_warnings", []) or []

        assert "images/test_image.jpg" in prompt
        assert "images/embedded_image.jpg" in prompt
        assert "images/ignored_image.jpg" in prompt
        assert "MISSING IMAGE: images/missing.jpg" in prompt
        assert "[IMAGE REF:" in prompt
        assert attached_count == 2
        assert any("Could not resolve embedded image" in item for item in warnings)

        await self.stop_system()
        self.teardown_scenario()


IMAGE_INPUT_POLICY_WORKFLOW = """---
workflow_engine: step
enabled: true
description: Validate image @input policy behavior
---

## STEP1
@model gpt-mini
@input file: images/test_image.jpg
@input file: images/ignored_image.jpg (images=ignore)
@input file: notes/with_image.md
@input file: notes/missing_image.md
@output variable: image_policy_buffer

Write a short note acknowledging receipt of the inputs.
"""


WITH_IMAGE_MD = """Here is an embedded image.

![Embedded test image](../images/embedded_image.jpg)

End of note.
"""


MISSING_IMAGE_MD = """Here is a missing embedded image.

![Missing test image](images/missing.jpg)
"""
