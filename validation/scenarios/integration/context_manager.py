"""
Integration scenario for validating context manager behavior via validation events.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ContextManagerScenario(BaseScenario):
    """Validate context manager basics and gating events."""

    async def test_scenario(self):
        vault = self.create_vault("ContextManagerVault")

        self.create_file(vault, "notes/seed.md", SEED_NOTE_CONTENT)
        self.create_file(
            vault,
            "AssistantMD/ContextTemplates/validation_context.md",
            VALIDATION_CONTEXT_TEMPLATE,
        )

        await self.start_system()

        checkpoint = self.event_checkpoint()
        first_payload = {
            "vault_name": vault.name,
            "prompt": "Summarize the seed note briefly.",
            "tools": [],
            "model": "gpt-mini",
            "context_template": "validation_context.md",
        }
        first_response = self.call_api("/api/chat/execute", method="POST", data=first_payload)
        assert first_response.status_code == 200, "Initial context-managed chat succeeds"
        session_id = first_response.json()["session_id"]
        assert session_id, "Session id should be returned"

        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_template_loaded",
            expected={"template_name": "validation_context.md", "template_source": "vault"},
        )
        self.assert_event_contains(
            events,
            name="context_input_files_resolved",
            expected={
                "section_name": "Summary",
                "file_count": 1,
                "files": [
                    {
                        "filepath": "notes/seed",
                        "content_preview": "Winter moonlight drifts, quiet code hums through the night, tests bloom with soft light.",
                    }
                ],
            },
        )
        self.assert_event_contains(
            events,
            name="context_input_files_resolved",
            expected={
                "section_name": "Recap",
                "file_count": 1,
                "files": [
                    {
                        "filepath": "variable: summary_buffer",
                        "found": True,
                    }
                ],
            },
        )
        self.assert_event_contains(
            events,
            name="context_section_completed",
            expected={"section_name": "Summary", "from_cache": False},
        )
        self.assert_event_contains(
            events,
            name="context_summary_persisted",
            expected={"sections": ["Summary", "Recap"]},
        )
        self.assert_event_contains(
            events,
            name="context_history_compiled",
            expected={
                "latest_user_included": True,
            },
        )

        self.create_file(
            vault,
            "AssistantMD/ContextTemplates/validation_context_threshold.md",
            VALIDATION_CONTEXT_TEMPLATE_THRESHOLD,
        )
        checkpoint = self.event_checkpoint()
        threshold_response = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "context_template": "validation_context_threshold.md",
                "prompt": "Threshold gate check.",
            },
        )
        assert threshold_response.status_code == 200, "Threshold-gated chat succeeds"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_template_skipped",
            expected={"template_name": "validation_context_threshold.md"},
        )

        checkpoint = self.event_checkpoint()
        second_response = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "session_id": session_id,
                "prompt": "Second turn to deepen the summary.",
            },
        )
        assert second_response.status_code == 200, "Follow-up context-managed chat succeeds"

        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_section_completed",
            expected={"section_name": "Summary", "from_cache": False},
        )
        self.assert_event_contains(
            events,
            name="context_recent_summaries_loaded",
            expected={"section_name": "Recap", "count": 1},
        )
        self.assert_event_contains(
            events,
            name="context_section_completed",
            expected={"section_name": "Recap", "from_cache": False},
        )
        self.assert_event_contains(
            events,
            name="context_history_compiled",
            expected={
                "latest_user_included": True,
            },
        )

        self.create_file(
            vault,
            "AssistantMD/ContextTemplates/validation_context_extended.md",
            VALIDATION_CONTEXT_TEMPLATE_EXTENDED,
        )
        checkpoint = self.event_checkpoint()
        extended_response = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "context_template": "validation_context_extended.md",
                "prompt": "Extended template checks.",
            },
        )
        assert extended_response.status_code == 200, "Extended context-managed chat succeeds"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_section_completed",
            expected={"section_name": "Output File", "from_cache": False},
        )
        self.assert_event_contains(
            events,
            name="context_section_skipped",
            expected={"section_name": "Required Skip", "reason": "input_file_required"},
        )
        self.assert_event_contains(
            events,
            name="context_llm_skipped",
            expected={"section_name": "Model None"},
        )
        self.assert_event_contains(
            events,
            name="context_section_completed",
            expected={"section_name": "Model None", "output_length": 0},
        )
        self.assert_event_contains(
            events,
            name="context_input_files_resolved",
            expected={
                "section_name": "Refs Only",
                "refs_only_count": 1,
                "missing_count": 0,
            },
        )
        output_path = vault / "outputs" / "managed_note.md"
        assert output_path.exists(), "Expected output file created by context manager"
        output_content = output_path.read_text(encoding="utf-8")
        assert "# Managed Header" in output_content, "Expected header in output file"

        await self.stop_system()
        self.teardown_scenario()


VALIDATION_CONTEXT_TEMPLATE = """---
passthrough_runs: 1
description: Validation template for context manager events.
---

## Summary
@recent-runs 1
@recent-summaries 0
@input file: notes/seed
@output variable: summary_buffer
@output context
@model gpt-mini

Summarize the seed-note haiku and the latest input in 2 bullets.
Call out any imagery or mood from the haiku.

## Recap
@recent-runs 2
@recent-summaries 1
@input variable: summary_buffer
@output context
@model gpt-mini

Restate the current topic in one sentence, referencing the haiku theme.

"""

VALIDATION_CONTEXT_TEMPLATE_THRESHOLD = """---
passthrough_runs: all
token_threshold: 999999
description: Validation template for global token threshold gating.
---

## Summary
@recent-runs 1
@recent-summaries 0
@input file: notes/seed
@model gpt-mini

Summarize the seed note in one sentence.
"""

VALIDATION_CONTEXT_TEMPLATE_EXTENDED = """---
passthrough_runs: 1
description: Validation template for extended context manager behaviors.
---

## Output File
@recent-runs 1
@recent-summaries 0
@input file: notes/seed
@output file: outputs/managed_note
@header Managed Header
@write-mode append
@model gpt-mini

Write one sentence about the seed note.

## Required Skip
@recent-runs 1
@recent-summaries 0
@input file: notes/missing (required)
@output context
@model gpt-mini

This section should be skipped when required input is missing.

## Model None
@recent-runs 1
@recent-summaries 0
@input file: notes/seed
@output context
@model none

This section should be skipped by the LLM.

## Refs Only
@recent-runs 1
@recent-summaries 0
@input file: notes/seed (refs-only)
@output context
@model gpt-mini

Summarize the seed note based on refs only.
"""

SEED_NOTE_CONTENT = "Winter moonlight drifts, quiet code hums through the night, tests bloom with soft light."
