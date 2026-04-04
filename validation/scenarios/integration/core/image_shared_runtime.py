"""
Integration scenario validating shared image-input behavior across authoring surfaces.

Covers direct image inputs, embedded markdown images, and images=ignore parity
between the string DSL and python_steps after input/prompt extraction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ImageSharedRuntimeScenario(BaseScenario):
    """Validate image prompt parity between DSL and python_steps."""

    async def test_scenario(self):
        vault = self.create_vault("ImageSharedRuntimeVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/image_shared_runtime_dsl.md",
            IMAGE_SHARED_RUNTIME_DSL_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/image_shared_runtime_sdk.md",
            IMAGE_SHARED_RUNTIME_SDK_WORKFLOW,
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

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "ImageSharedRuntimeVault/image_shared_runtime_dsl"},
        )
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "ImageSharedRuntimeVault/image_shared_runtime_sdk"},
        )

        checkpoint = self.event_checkpoint()
        dsl_result = await self.run_workflow(vault, "image_shared_runtime_dsl")
        self.soft_assert_equal(dsl_result.status, "completed", "DSL image workflow should succeed")
        dsl_events = self.events_since(checkpoint)

        dsl_auto = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "AUTO_IMAGES"},
        )
        dsl_auto_data = (dsl_auto or {}).get("data", {})
        dsl_auto_prompt = dsl_auto_data.get("prompt", "")
        self.soft_assert("images/test_image.jpg" in dsl_auto_prompt, "DSL auto prompt should reference direct image")
        self.soft_assert("embedded_image.jpg" in dsl_auto_prompt, "DSL auto prompt should reference embedded image")
        self.soft_assert("(deduped)" in dsl_auto_prompt, "DSL auto prompt should show embedded-image dedupe")
        self.soft_assert_equal(
            dsl_auto_data.get("attached_image_count", 0),
            1,
            "DSL auto prompt should dedupe identical direct and embedded images",
        )

        dsl_ignore = self.assert_event_contains(
            dsl_events,
            name="workflow_step_prompt",
            expected={"step_name": "IGNORE_IMAGE"},
        )
        dsl_ignore_data = (dsl_ignore or {}).get("data", {})
        self.soft_assert("images/ignored_image.jpg" in dsl_ignore_data.get("prompt", ""), "DSL ignore prompt should reference image path")
        self.soft_assert_equal(
            dsl_ignore_data.get("attached_image_count", 0),
            0,
            "DSL images=ignore should suppress attachments",
        )

        checkpoint = self.event_checkpoint()
        sdk_result = await self.run_workflow(vault, "image_shared_runtime_sdk")
        self.soft_assert_equal(sdk_result.status, "completed", "SDK image workflow should succeed")
        sdk_events = self.events_since(checkpoint)

        sdk_auto = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "auto_images"},
        )
        sdk_auto_data = (sdk_auto or {}).get("data", {})
        sdk_auto_prompt = sdk_auto_data.get("prompt", "")
        self.soft_assert("images/test_image.jpg" in sdk_auto_prompt, "SDK auto prompt should reference direct image")
        self.soft_assert("embedded_image.jpg" in sdk_auto_prompt, "SDK auto prompt should reference embedded image")
        self.soft_assert("(deduped)" in sdk_auto_prompt, "SDK auto prompt should show embedded-image dedupe")
        self.soft_assert_equal(
            sdk_auto_data.get("attached_image_count", 0),
            1,
            "SDK auto prompt should dedupe identical direct and embedded images",
        )

        sdk_ignore = self.assert_event_contains(
            sdk_events,
            name="python_step_prompt",
            expected={"step_name": "ignore_image"},
        )
        sdk_ignore_data = (sdk_ignore or {}).get("data", {})
        self.soft_assert("images/ignored_image.jpg" in sdk_ignore_data.get("prompt", ""), "SDK ignore prompt should reference image path")
        self.soft_assert_equal(
            sdk_ignore_data.get("attached_image_count", 0),
            0,
            "SDK images=ignore should suppress attachments",
        )

        await self.stop_system()
        self.teardown_scenario()


IMAGE_SHARED_RUNTIME_DSL_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Shared runtime image parity DSL coverage
---

## AUTO_IMAGES
@model test
@input file: images/test_image.jpg
@input file: notes/with_image.md
@output variable: auto_images_buffer

Confirm the image inputs were included.

## IGNORE_IMAGE
@model test
@input file: images/ignored_image.jpg (images=ignore)
@output variable: ignore_images_buffer

Confirm the ignored image input was reference-only.
"""


IMAGE_SHARED_RUNTIME_SDK_WORKFLOW = """---
workflow_engine: python_steps
enabled: false
description: Shared runtime image parity SDK coverage
---

```python
auto_images = Step(
    name="auto_images",
    model="test",
    inputs=[
        File("images/test_image.jpg"),
        File("notes/with_image.md"),
    ],
    output=Var("auto_images_buffer"),
    prompt="Confirm the image inputs were included.",
)

ignore_image = Step(
    name="ignore_image",
    model="test",
    inputs=[
        File("images/ignored_image.jpg", images="ignore"),
    ],
    output=Var("ignore_images_buffer"),
    prompt="Confirm the ignored image input was reference-only.",
)

workflow = Workflow(
    steps=[auto_images, ignore_image],
)

workflow.run()
```
"""


WITH_IMAGE_MD = """Here is an embedded image.

![Embedded test image](../images/embedded_image.jpg)

End of note.
"""
