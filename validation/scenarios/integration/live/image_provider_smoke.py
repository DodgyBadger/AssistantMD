"""
Live multimodal smoke scenario.

Executes one real image-enabled call to verify provider compatibility for direct
image inputs end-to-end.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ImageProviderSmokeScenario(BaseScenario):
    """Minimal real-provider image smoke coverage."""

    async def test_scenario(self):
        vault = self.create_vault("ImageProviderSmokeVault")

        self.copy_files("validation/templates/files/test_image.jpg", vault, "images")
        self.create_file(
            vault,
            "AssistantMD/Workflows/image_provider_smoke.md",
            IMAGE_PROVIDER_SMOKE_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()

        result = await self.run_workflow(vault, "image_provider_smoke")
        assert result.status == "completed", result.error_message

        events = self.events_since(checkpoint)
        prompt_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP1"},
        )
        prompt_data = prompt_event.get("data", {})
        attached_count = prompt_data.get("attached_image_count", 0)
        assert attached_count >= 1, "Expected at least one attached image"

        output_path = vault / "outputs" / "image-provider-smoke.md"
        assert output_path.exists(), "Expected live smoke output artifact"
        assert output_path.stat().st_size > 0, "Live smoke output artifact is empty"

        await self.stop_system()
        self.teardown_scenario()


IMAGE_PROVIDER_SMOKE_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Minimal live image provider smoke
---

## STEP1
@model gpt-mini
@input file: images/test_image.jpg
@output file: outputs/image-provider-smoke

Write one short sentence describing the image.
"""
