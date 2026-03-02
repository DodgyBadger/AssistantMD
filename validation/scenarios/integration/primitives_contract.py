"""
Integration scenario for comprehensive primitive contract coverage.

Covers core workflow primitives documented in docs/use/reference.md using
deterministic execution (@model test / @model none) and validation events.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PrimitivesContractScenario(BaseScenario):
    """Validate frontmatter, directive, and pattern primitives end-to-end."""

    def _event(self, events, *, name: str, expected: dict):
        return self.soft_assert_event_contains(events, name=name, expected=expected)

    def _prompt_for_step(self, events, step_name: str) -> str:
        event = self._event(
            events,
            name="workflow_step_prompt",
            expected={"step_name": step_name},
        )
        return (event or {}).get("data", {}).get("prompt", "")

    def _read_if_exists(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _assert_contains(self, content: str, needle: str, message: str):
        self.soft_assert(needle in content, message)

    def _assert_not_contains(self, content: str, needle: str, message: str):
        self.soft_assert(needle not in content, message)

    async def test_scenario(self):
        vault = self.create_vault("PrimitivesContractVault")

        # Seed files used by @input behaviors.
        self.create_file(vault, "notes/plain.md", "PLAIN_BODY")
        self.create_file(
            vault,
            "notes/with_props.md",
            (
                "---\n"
                "status: active\n"
                "owner: alice\n"
                "priority: high\n"
                "---\n\n"
                "BODY_SHOULD_NOT_APPEAR"
            ),
        )
        self.create_file(
            vault,
            "notes/long_note.md",
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        )
        self.create_file(vault, "timeline/2026-03-01.md", "OLDER_ENTRY")
        self.create_file(vault, "timeline/2026-03-02.md", "LATEST_ENTRY")
        self.create_file(vault, "tasks/task1.md", "Task 1")
        self.create_file(vault, "tasks/task2.md", "Task 2")

        self.create_file(
            vault,
            "AssistantMD/Workflows/primitives_contract.md",
            PRIMITIVES_CONTRACT_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/ContextTemplates/primitives_context.md",
            PRIMITIVES_CONTEXT_TEMPLATE,
        )
        self.create_file(
            vault,
            "AssistantMD/ContextTemplates/primitives_context_threshold.md",
            PRIMITIVES_CONTEXT_THRESHOLD_TEMPLATE,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()

        startup_events = self.events_since(checkpoint)
        self._event(
            startup_events,
            name="workflow_loaded",
            expected={
                "workflow_id": "PrimitivesContractVault/primitives_contract",
                "enabled": True,
                "schedule": "cron: 0 9 * * *",
            },
        )
        self._event(
            startup_events,
            name="job_synced",
            expected={
                "job_id": "PrimitivesContractVault__primitives_contract",
                "action": "created",
            },
        )

        # Monday with week_start_day=sunday -> {this-week} resolves to 2026-03-01.
        self.set_date("2026-03-02")

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "primitives_contract")
        self.soft_assert_equal(
            result.status,
            "completed",
            "Primitive contract workflow should complete",
        )
        events = self.events_since(checkpoint)

        # Step skipping primitives.
        self._event(
            events,
            name="workflow_step_skipped",
            expected={"step_name": "RUN_ON_NEVER", "reason": "run_on"},
        )
        self._event(
            events,
            name="workflow_step_skipped",
            expected={"step_name": "MODEL_NONE", "reason": "model_none"},
        )
        self._event(
            events,
            name="workflow_step_skipped",
            expected={"step_name": "REQUIRED_SKIP"},
        )

        # @input properties mode.
        properties_prompt = self._prompt_for_step(events, "INPUT_PROPERTIES")
        self._assert_contains(properties_prompt, "status: active", "Expected status property in prompt")
        self._assert_contains(properties_prompt, "owner: alice", "Expected owner property in prompt")
        self._assert_not_contains(properties_prompt, "BODY_SHOULD_NOT_APPEAR", "Body content should not appear in properties mode")

        # @input head mode.
        head_prompt = self._prompt_for_step(events, "INPUT_HEAD")
        self._assert_contains(head_prompt, "ABCDEFGHIJKL", "Expected head=12 content in prompt")
        self._assert_not_contains(head_prompt, "MNOPQRSTUVWXYZ", "Expected prompt to exclude characters beyond head=12")

        # @input refs_only mode.
        refs_prompt = self._prompt_for_step(events, "INPUT_REFS_ONLY")
        self._assert_contains(refs_prompt, "- notes/plain", "Expected refs-only path listing")
        self._assert_not_contains(refs_prompt, "PLAIN_BODY", "Refs-only prompt should not inline content")

        # @input pattern modes: latest + latest:N.
        latest_one_prompt = self._prompt_for_step(events, "LATEST_ONE")
        self._assert_contains(latest_one_prompt, "LATEST_ENTRY", "Expected latest file content")
        self._assert_not_contains(latest_one_prompt, "OLDER_ENTRY", "Expected {latest} to resolve to a single most recent file")

        latest_two_prompt = self._prompt_for_step(events, "LATEST_TWO")
        self._assert_contains(latest_two_prompt, "LATEST_ENTRY", "Expected newest entry in {latest:2}")
        self._assert_contains(latest_two_prompt, "OLDER_ENTRY", "Expected older entry in {latest:2}")

        # @input output routing.
        self._event(
            events,
            name="input_routed",
            expected={
                "destination": "variable: routed_input",
                "refs_only": False,
                "item_count": 1,
            },
        )
        routed_prompt = self._prompt_for_step(events, "INPUT_ROUTED")
        self._assert_contains(routed_prompt, "PLAIN_BODY", "Expected routed variable content in prompt")

        # {pending} contract: first run resolves files, second run resolves none.
        self._event(
            events,
            name="pending_files_resolved",
            expected={
                "pattern": "tasks/{pending:2}",
                "pending_count": 2,
            },
        )
        self._event(
            events,
            name="pending_files_resolved",
            expected={
                "pattern": "tasks/{pending:2}",
                "pending_count": 0,
            },
        )

        # Output artifacts validate @output, @header, @write_mode, and pattern substitutions.
        run_on_daily = vault / "outputs" / "run-on-daily.md"
        self.soft_assert(run_on_daily.exists(), "Daily run_on step should write output")

        model_none_output = vault / "outputs" / "model-none.md"
        self.soft_assert(not model_none_output.exists(), "@model none step should not write output")

        required_skip_output = vault / "outputs" / "required-skip.md"
        self.soft_assert(
            not required_skip_output.exists(),
            "Required-missing input should skip output write",
        )

        mode_target = vault / "outputs" / "mode-target.md"
        mode_target_new = vault / "outputs" / "mode-target_000.md"
        self.soft_assert(mode_target.exists(), "Expected main write-mode target file")
        self.soft_assert(mode_target_new.exists(), "Expected numbered file from write_mode=new")

        mode_target_content = self._read_if_exists(mode_target)
        mode_target_new_content = self._read_if_exists(mode_target_new)
        self._assert_contains(mode_target_content, "# Replace 20260302", "Expected replace header")
        self._assert_contains(mode_target_content, "# Append Mon", "Expected append header with day token")
        self._assert_contains(mode_target_new_content, "# New 2026-03-01", "Expected new-mode numbered file header")

        pattern_file = vault / "outputs" / "month-2026-03.md"
        self.soft_assert(pattern_file.exists(), "Expected pattern-substituted output path")
        pattern_content = self._read_if_exists(pattern_file)
        self._assert_contains(pattern_content, "# Pattern March Monday", "Expected month/day-name token substitution in header")

        # Context-template primitives: passthrough/token-threshold/cache/recent-runs/recent-summaries.
        checkpoint = self.event_checkpoint()
        first_chat = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                "vault_name": vault.name,
                "prompt": "Context primitives first turn.",
                "tools": [],
                "model": "test",
                "context_template": "primitives_context.md",
            },
        )
        self.soft_assert_equal(first_chat.status_code, 200, "First context chat should succeed")
        first_payload = first_chat.json() if first_chat.status_code == 200 else {}
        session_id = first_payload.get("session_id")
        self.soft_assert(bool(session_id), "Context chat should return session_id")

        context_events_first = self.events_since(checkpoint)
        self._event(
            context_events_first,
            name="context_template_loaded",
            expected={
                "template_name": "primitives_context.md",
                "template_source": "vault",
                "passthrough_runs": 1,
            },
        )
        self._event(
            context_events_first,
            name="context_cache_miss",
            expected={
                "section_name": "Cache Session",
                "cache_mode": "session",
            },
        )
        self._event(
            context_events_first,
            name="context_section_completed",
            expected={
                "section_name": "Cache Session",
                "from_cache": False,
            },
        )
        self._event(
            context_events_first,
            name="context_recent_summaries_loaded",
            expected={"section_name": "Recent Summary Section"},
        )
        self._event(
            context_events_first,
            name="context_llm_skipped",
            expected={"section_name": "Model None Section"},
        )
        self._event(
            context_events_first,
            name="context_section_completed",
            expected={
                "section_name": "Model None Section",
                "output_length": 0,
            },
        )
        self._event(
            context_events_first,
            name="context_input_files_resolved",
            expected={
                "section_name": "Inline To Context",
                "file_count": 1,
            },
        )

        checkpoint = self.event_checkpoint()
        second_chat = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                "vault_name": vault.name,
                "prompt": "Context primitives second turn.",
                "tools": [],
                "model": "test",
                "session_id": session_id,
                "context_template": "primitives_context.md",
            },
        )
        self.soft_assert_equal(second_chat.status_code, 200, "Second context chat should succeed")
        context_events_second = self.events_since(checkpoint)
        self._event(
            context_events_second,
            name="context_cache_hit",
            expected={
                "section_name": "Cache Session",
                "cache_mode": "session",
                "cache_scope": "persistent",
            },
        )
        self._event(
            context_events_second,
            name="context_section_completed",
            expected={
                "section_name": "Cache Session",
                "from_cache": True,
            },
        )
        self._event(
            context_events_second,
            name="context_recent_summaries_loaded",
            expected={
                "section_name": "Recent Summary Section",
                "count": 1,
            },
        )

        checkpoint = self.event_checkpoint()
        threshold_chat = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                "vault_name": vault.name,
                "prompt": "Threshold gate check.",
                "tools": [],
                "model": "test",
                "context_template": "primitives_context_threshold.md",
            },
        )
        self.soft_assert_equal(
            threshold_chat.status_code,
            200,
            "Threshold-gated context chat should succeed",
        )
        threshold_events = self.events_since(checkpoint)
        self._event(
            threshold_events,
            name="context_template_skipped",
            expected={"template_name": "primitives_context_threshold.md"},
        )

        await self.stop_system()
        self.teardown_scenario()


PRIMITIVES_CONTRACT_WORKFLOW = """---
schedule: cron: 0 9 * * *
workflow_engine: step
enabled: true
week_start_day: sunday
description: Primitive contract coverage
team: validation
---

## RUN_ON_DAILY
@model test
@run_on daily
@output file: outputs/run-on-daily

Daily step should run.

## RUN_ON_NEVER
@model test
@run_on never
@output file: outputs/run-on-never

Never step should be skipped.

## MODEL_NONE
@model none
@output file: outputs/model-none

This step skips LLM execution.

## INPUT_PROPERTIES
@model test
@input file: notes/with_props (properties="status,owner")
@output variable: props_buffer

Summarize properties.

## INPUT_HEAD
@model test
@input file: notes/long_note (head=12)
@output variable: head_buffer

Summarize head slice.

## INPUT_REFS_ONLY
@model test
@input file: notes/plain (refs_only)
@output variable: refs_buffer

Summarize refs only.

## REQUIRED_SKIP
@model test
@input file: notes/missing (required)
@output file: outputs/required-skip

Should skip due to required missing input.

## LATEST_ONE
@model test
@input file: timeline/{latest}
@output variable: latest_one

Summarize latest file.

## LATEST_TWO
@model test
@input file: timeline/{latest:2}
@output variable: latest_two

Summarize latest two files.

## INPUT_ROUTED
@model test
@input file: notes/plain (output=variable: routed_input, write_mode=replace)
@input variable: routed_input
@output file: outputs/routed-input

Confirm routed input content.

## PENDING_FIRST
@model test
@input file: tasks/{pending:2}
@output file: outputs/pending-first

Process pending files once.

## PENDING_SECOND
@model test
@input file: tasks/{pending:2}
@output file: outputs/pending-second

Pending should now be empty.

## WRITE_REPLACE
@model test
@output file: outputs/mode-target
@write_mode replace
@header Replace {today:YYYYMMDD}

Write replace mode output.

## WRITE_APPEND
@model test
@output file: outputs/mode-target
@write_mode append
@header Append {day-name:ddd}

Write append mode output.

## WRITE_NEW
@model test
@output file: outputs/mode-target
@write_mode new
@header New {this-week}

Write new mode output.

## TOOLS_DIRECTIVE_PARSE
@model test
@tools file_ops_safe(output=variable: tool_buffer, write_mode=replace)
@output file: outputs/tools-directive

Use tool directives in deterministic mode.

## PATTERN_OUTPUT_HEADER
@model test
@output file: outputs/month-{this-month}
@header Pattern {month-name} {day-name}

Validate month/day substitution in output and header.
"""


PRIMITIVES_CONTEXT_TEMPLATE = """---
passthrough_runs: 1
token_threshold: 0
week_start_day: sunday
description: Context primitive coverage
---

## Cache Session
@recent_runs 1
@recent_summaries 0
@input file: notes/plain
@output variable: shared_summary (scope=session)
@output context
@cache session
@model test

Summarize the note.

## Recent Summary Section
@recent_runs 1
@recent_summaries 1
@input variable: shared_summary (scope=session)
@output context
@model test

Restate prior summary.

## Inline To Context
@recent_runs 0
@input file: notes/plain (output=context)
@output context
@model none

Inline note into context without LLM.

## Model None Section
@recent_runs 0
@output context
@model none

Skip model execution.
"""


PRIMITIVES_CONTEXT_THRESHOLD_TEMPLATE = """---
passthrough_runs: 1
token_threshold: 999999
description: Threshold gate template
---

## Threshold Section
@recent_runs 1
@model test
@output context

This should be skipped by token threshold.
"""
