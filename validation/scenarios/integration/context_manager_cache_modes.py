"""
Integration scenario for validating cache modes and invalidation in context manager.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ContextManagerCacheModesScenario(BaseScenario):
    """Validate cache modes, expiry, session behavior, and template invalidation."""

    async def test_scenario(self):
        vault = self.create_vault("ContextCacheVault")

        self.create_file(vault, "notes/seed.md", SEED_NOTE_CONTENT)
        self.create_file(
            vault,
            "AssistantMD/ContextTemplates/cache_modes.md",
            CACHE_MODES_TEMPLATE,
        )

        await self.start_system()

        base_now = datetime.now(timezone.utc)
        self.set_context_manager_now(base_now)

        checkpoint = self.event_checkpoint()
        first_payload = {
            "vault_name": vault.name,
            "prompt": "Summarize the seed note briefly.",
            "tools": [],
            "model": "gpt-mini",
            "context_template": "cache_modes.md",
        }
        first_response = self.call_api("/api/chat/execute", method="POST", data=first_payload)
        assert first_response.status_code == 200, "Initial context-managed chat succeeds"
        session_id = first_response.json().get("session_id")
        assert session_id, "Expected session id for cache checks"

        events = self.events_since(checkpoint)
        first_hashes = {}
        for section_name, cache_mode in [
            ("Daily Summary", "daily"),
            ("Weekly Summary", "weekly"),
            ("Duration Summary", "duration"),
            ("Session Summary", "session"),
        ]:
            self.assert_event_contains(
                events,
                name="context_cache_miss",
                expected={"section_name": section_name, "cache_mode": cache_mode},
            )
            self.assert_event_contains(
                events,
                name="context_section_completed",
                expected={"section_name": section_name, "from_cache": False},
            )
            completed = self.latest_event(
                events,
                name="context_section_completed",
                section_name=section_name,
            )
            assert completed, f"Expected completion event for {section_name}"
            output_hash = completed.get("data", {}).get("output_hash")
            assert output_hash, f"Expected output hash for {section_name}"
            first_hashes[section_name] = output_hash

        checkpoint = self.event_checkpoint()
        session_response = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "session_id": session_id,
                "prompt": "Session cache hit check.",
            },
        )
        assert session_response.status_code == 200, "Session cache hit check succeeds"
        events = self.events_since(checkpoint)
        session_hit = self.assert_event_contains(
            events,
            name="context_cache_hit",
            expected={
                "section_name": "Session Summary",
                "cache_mode": "session",
                "cache_scope": "persistent",
            },
        )
        cached_hash = session_hit.get("data", {}).get("output_hash")
        assert cached_hash == first_hashes.get("Session Summary"), (
            "Expected cached session output hash to match first run"
        )

        await self.restart_system()
        self.set_context_manager_now(base_now)

        checkpoint = self.event_checkpoint()
        second_response = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "prompt": "Second run after restart to test cache hits.",
            },
        )
        assert second_response.status_code == 200, "Follow-up context-managed chat succeeds"

        events = self.events_since(checkpoint)
        for section_name, cache_mode in [
            ("Daily Summary", "daily"),
            ("Weekly Summary", "weekly"),
            ("Duration Summary", "duration"),
        ]:
            cache_hit = self.assert_event_contains(
                events,
                name="context_cache_hit",
                expected={
                    "section_name": section_name,
                    "cache_mode": cache_mode,
                    "cache_scope": "persistent",
                },
            )
            cached_hash = cache_hit.get("data", {}).get("output_hash")
            assert cached_hash == first_hashes.get(section_name), (
                f"Expected cached output hash to match first run for {section_name}"
            )
            self.assert_event_contains(
                events,
                name="context_section_completed",
                expected={"section_name": section_name, "from_cache": True},
            )
        self.assert_event_contains(
            events,
            name="context_cache_miss",
            expected={"section_name": "Session Summary", "cache_mode": "session"},
        )

        self.set_context_manager_now(base_now + timedelta(days=1))
        checkpoint = self.event_checkpoint()
        daily_expired = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "prompt": "Daily expiry check.",
            },
        )
        assert daily_expired.status_code == 200, "Daily expiry validation chat succeeds"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_cache_miss",
            expected={
                "section_name": "Daily Summary",
                "cache_mode": "daily",
                "reason": "expired",
            },
        )
        self.assert_event_contains(
            events,
            name="context_llm_invoked",
            expected={"section_name": "Daily Summary"},
        )

        self.set_context_manager_now(base_now + timedelta(days=7))
        checkpoint = self.event_checkpoint()
        weekly_expired = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "prompt": "Weekly expiry check.",
            },
        )
        assert weekly_expired.status_code == 200, "Weekly expiry validation chat succeeds"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_cache_miss",
            expected={
                "section_name": "Weekly Summary",
                "cache_mode": "weekly",
                "reason": "expired",
            },
        )
        self.assert_event_contains(
            events,
            name="context_llm_invoked",
            expected={"section_name": "Weekly Summary"},
        )

        self.set_context_manager_now(base_now + timedelta(hours=2))
        checkpoint = self.event_checkpoint()
        third_response = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "prompt": "Third run to confirm duration cache expiry.",
            },
        )
        assert third_response.status_code == 200, "Expiry validation chat succeeds"

        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_cache_miss",
            expected={
                "section_name": "Duration Summary",
                "cache_mode": "duration",
                "reason": "expired",
            },
        )
        self.assert_event_contains(
            events,
            name="context_llm_invoked",
            expected={"section_name": "Duration Summary"},
        )
        self.assert_event_contains(
            events,
            name="context_section_completed",
            expected={"section_name": "Duration Summary", "from_cache": False},
        )

        self.create_file(
            vault,
            "AssistantMD/ContextTemplates/cache_modes.md",
            CACHE_MODES_TEMPLATE_V2,
        )
        checkpoint = self.event_checkpoint()
        template_changed = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **first_payload,
                "prompt": "Template change invalidation check.",
            },
        )
        assert template_changed.status_code == 200, "Template invalidation chat succeeds"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="context_cache_miss",
            expected={
                "section_name": "Daily Summary",
                "cache_mode": "daily",
                "reason": "template_changed",
            },
        )
        self.assert_event_contains(
            events,
            name="context_llm_invoked",
            expected={"section_name": "Daily Summary"},
        )

        await self.stop_system()
        self.teardown_scenario()


CACHE_MODES_TEMPLATE = """---
passthrough_runs: 1
description: Validation template for cache modes.
---

## Daily Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache daily
@model gpt-mini

Summarize the haiku imagery in one short sentence.

## Weekly Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache weekly
@model gpt-mini

Summarize the haiku mood in one short sentence.

## Duration Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache 5m
@model gpt-mini

Summarize the haiku setting in one short sentence.

## Session Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache session
@model gpt-mini

Summarize the haiku in one short sentence.
"""

CACHE_MODES_TEMPLATE_V2 = """---
passthrough_runs: 1
description: Validation template for cache modes (v2).
---

## Daily Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache daily
@model gpt-mini

Summarize the haiku imagery in one short sentence, focusing on light.

## Weekly Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache weekly
@model gpt-mini

Summarize the haiku mood in one short sentence.

## Duration Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache 5m
@model gpt-mini

Summarize the haiku setting in one short sentence.

## Session Summary
@recent-runs 1
@recent-summaries 0
@input-file notes/seed
@cache session
@model gpt-mini

Summarize the haiku in one short sentence.
"""

SEED_NOTE_CONTENT = "Winter moonlight drifts, quiet code hums through the night, tests bloom with soft light."
