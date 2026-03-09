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
        self.copy_files(
            "validation/templates/files/test_image.jpg",
            vault,
            "pages",
            dest_filename="2026-03-01.jpg",
        )
        self.copy_files(
            "validation/templates/files/test_image.jpg",
            vault,
            "pages",
            dest_filename="2026-03-02.jpg",
        )
        self.copy_files(
            "validation/templates/files/test_image.jpg",
            vault,
            "pending-pages",
            dest_filename="page-01.jpg",
        )
        self.copy_files(
            "validation/templates/files/test_image.jpg",
            vault,
            "pending-pages",
            dest_filename="page-02.jpg",
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

        step3_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP3_LATEST_SELECTOR"},
        )
        step3_data = step3_event.get("data", {})
        step3_prompt = step3_data.get("prompt", "")
        step3_attached = step3_data.get("attached_image_count", 0)
        assert "pages/2026-03-02.jpg" in step3_prompt
        assert "pages/2026-03-01.jpg" in step3_prompt
        assert "(deduped)" in step3_prompt
        assert step3_attached == 1

        step4_event = self.assert_event_contains(
            events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP4_PENDING_SELECTOR"},
        )
        step4_data = step4_event.get("data", {})
        step4_prompt = step4_data.get("prompt", "")
        step4_attached = step4_data.get("attached_image_count", 0)
        assert "pending-pages/page-01.jpg" in step4_prompt
        assert "pending-pages/page-02.jpg" in step4_prompt
        assert "(deduped)" in step4_prompt
        assert step4_attached == 1

        pending_resolved = self.assert_event_contains(
            events,
            name="pending_files_resolved",
            expected={"pending_count": 2},
        )
        pending_paths = pending_resolved.get("data", {}).get("pending_paths", [])
        assert "pending-pages/page-01.jpg" in pending_paths
        assert "pending-pages/page-02.jpg" in pending_paths

        second_checkpoint = self.event_checkpoint()
        second_result = await self.run_workflow(
            vault,
            "image_contract",
            step_name="STEP4_PENDING_SELECTOR",
        )
        assert second_result.status == "completed", second_result.error_message

        second_events = self.events_since(second_checkpoint)
        second_step4 = self.assert_event_contains(
            second_events,
            name="workflow_step_prompt",
            expected={"step_name": "STEP4_PENDING_SELECTOR"},
        )
        second_step4_data = second_step4.get("data", {})
        assert second_step4_data.get("attached_image_count", 0) == 0

        second_pending = self.assert_event_contains(
            second_events,
            name="pending_files_resolved",
            expected={"pending_count": 0},
        )
        assert second_pending.get("data", {}).get("pending_paths", []) == []

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

## STEP3_LATEST_SELECTOR
@model test
@input file: pages/*.jpg (latest, limit=2, order=filename_dt, dt_pattern="(\\d{4}-\\d{2}-\\d{2})", dt_format="YYYY-MM-DD")
@output variable: latest_selector_buffer

Confirm the latest image selector included both page images.

## STEP4_PENDING_SELECTOR
@model test
@input file: pending-pages/*.jpg (pending, order=alphanum, dir=asc, limit=10)
@output variable: pending_selector_buffer

Confirm the pending image selector included all unprocessed page images.
"""


WITH_IMAGE_MD = """Here is an embedded image.

![Embedded test image](../images/embedded_image.jpg)

End of note.
"""


MISSING_IMAGE_MD = """Here is a missing embedded image.

![Missing test image](images/missing.jpg)
"""
