"""
Integration scenario for current Monty helper contract coverage.

Validates the current tool-first authoring surface using deterministic model
execution and stable validation events.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class AuthoringContractScenario(BaseScenario):
    """Validate the implemented Monty host contract end to end."""

    async def test_scenario(self):
        vault = self.create_vault("AuthoringContractVault")

        self.create_file(vault, "notes/seed.md", "SEED_CONTENT")
        self.copy_files("validation/templates/files/test_image.jpg", vault, "images")
        self.create_file(vault, "notes/structured.md", STRUCTURED_NOTE)
        self.create_file(vault, "tasks/pending-one.md", "PENDING_ONE")

        self.create_file(
            vault,
            "AssistantMD/Authoring/authoring_contract_success.md",
            AUTHORING_CONTRACT_SUCCESS_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Authoring/authoring_generate_cache_daily.md",
            AUTHORING_GENERATE_CACHE_DAILY_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()
        startup_events = self.events_since(checkpoint)
        self.assert_event_contains(
            startup_events,
            name="workflow_loaded",
            expected={"workflow_id": "AuthoringContractVault/authoring_contract_success"},
        )

        self.set_date("2026-04-06")

        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, "authoring_contract_success")
        self.soft_assert_equal(result.status, "completed", "Contract success workflow should complete")
        events = self.events_since(checkpoint)

        self.assert_event_contains(
            events,
            name="authoring_monty_execution_started",
            expected={"workflow_id": "AuthoringContractVault/authoring_contract_success"},
        )
        self.assert_event_contains(
            events,
            name="authoring_call_tool_started",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "tool": "file_ops_safe",
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_call_tool_completed",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "tool": "file_ops_safe",
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_generate_started",
            expected={"workflow_id": "AuthoringContractVault/authoring_contract_success"},
        )
        self.assert_event_contains(
            events,
            name="authoring_generate_completed",
            expected={"workflow_id": "AuthoringContractVault/authoring_contract_success"},
        )
        self.assert_event_contains(
            events,
            name="authoring_assemble_context_completed",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "message_count": 3,
                "instruction_count": 1,
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_parse_markdown_started",
            expected={"workflow_id": "AuthoringContractVault/authoring_contract_success"},
        )
        self.assert_event_contains(
            events,
            name="authoring_parse_markdown_completed",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "heading_count": 2,
                "section_count": 2,
                "code_block_count": 1,
                "image_count": 1,
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_pending_files_filtered",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "pending_count": 1,
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_pending_files_completed",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "completed_count": 1,
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_finish_requested",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "status": "completed",
                "reason": "all-helpers-exercised",
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_monty_execution_completed",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "status": "completed",
                "reason": "all-helpers-exercised",
            },
        )

        contract_output = vault / "outputs" / "contract-success.md"
        self.soft_assert(contract_output.exists(), "Expected contract success output file")
        if contract_output.exists():
            content = contract_output.read_text(encoding="utf-8")
            self.soft_assert("SEED_CONTENT" in content, "Expected retrieved file content in output")
            self.soft_assert("ASSEMBLED=3" in content, "Expected assembled context count in output")

        generated_output = vault / "outputs" / "generate-success.md"
        self.soft_assert(generated_output.exists(), "Expected generate output file")
        if generated_output.exists():
            self.soft_assert(
                generated_output.stat().st_size > 0,
                "Expected generate output file to be non-empty",
            )
        parsed_output = vault / "outputs" / "parse-markdown.md"
        self.soft_assert(parsed_output.exists(), "Expected markdown parse output file")
        if parsed_output.exists():
            parsed_content = parsed_output.read_text(encoding="utf-8")
            self.soft_assert("Skill Example" in parsed_content, "Expected parsed frontmatter name in output")
            self.soft_assert("AI In Fiction" in parsed_content, "Expected parsed section heading in output")
            self.soft_assert("python" in parsed_content, "Expected parsed code block language in output")
            self.soft_assert("../images/test_image.jpg" in parsed_content, "Expected parsed image ref in output")

        # Generate-level cache semantics should skip repeated LLM work within the TTL window.
        self.set_date("2026-04-06")
        checkpoint = self.event_checkpoint()
        first_generate_cache = await self.run_workflow(vault, "authoring_generate_cache_daily")
        self.soft_assert_equal(
            first_generate_cache.status,
            "completed",
            "First generate cache workflow run should succeed",
        )
        generate_cache_status = vault / "outputs" / "generate-cache-status.md"
        self.soft_assert(
            generate_cache_status.read_text(encoding="utf-8").strip() == "status=generated",
            "First generate cache run should produce a fresh generation",
        )
        generate_cache_events = self.events_since(checkpoint)
        self.assert_event_contains(
            generate_cache_events,
            name="authoring_generate_started",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_generate_cache_daily",
                "cache_mode": "daily",
            },
        )
        self.assert_event_contains(
            generate_cache_events,
            name="authoring_generate_cache_stored",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_generate_cache_daily",
                "cache_mode": "daily",
            },
        )

        checkpoint = self.event_checkpoint()
        second_generate_cache = await self.run_workflow(vault, "authoring_generate_cache_daily")
        self.soft_assert_equal(
            second_generate_cache.status,
            "completed",
            "Second same-day generate cache workflow run should succeed",
        )
        self.soft_assert(
            generate_cache_status.read_text(encoding="utf-8").strip() == "status=cached",
            "Second same-day generate cache run should hit cache",
        )
        generate_cache_events = self.events_since(checkpoint)
        self.assert_event_contains(
            generate_cache_events,
            name="authoring_generate_cache_hit",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_generate_cache_daily",
                "cache_mode": "daily",
            },
        )

        self.set_date("2026-04-07")
        checkpoint = self.event_checkpoint()
        third_generate_cache = await self.run_workflow(vault, "authoring_generate_cache_daily")
        self.soft_assert_equal(
            third_generate_cache.status,
            "completed",
            "Next-day generate cache workflow run should succeed",
        )
        self.soft_assert(
            generate_cache_status.read_text(encoding="utf-8").strip() == "status=generated",
            "Next-day generate cache run should treat daily generation cache as expired",
        )
        generate_cache_events = self.events_since(checkpoint)
        self.assert_event_contains(
            generate_cache_events,
            name="authoring_generate_started",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_generate_cache_daily",
                "cache_mode": "daily",
            },
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()


AUTHORING_CONTRACT_SUCCESS_WORKFLOW_TEMPLATE = """---
workflow_engine: monty
enabled: false
description: Deterministic authoring contract success workflow
---

## Run

```python
def _strip_read_output(value):
    return value.split("\\n\\n", 1)[1] if "\\n\\n" in value else value


async def _write_replace(path, content):
    existing = await call_tool(
        name="file_ops_safe",
        arguments={"operation": "read", "path": path},
    )
    if existing.metadata.get("status") == "completed":
        await call_tool(
            name="file_ops_unsafe",
            arguments={"operation": "truncate", "path": path, "confirm_path": path},
        )
        await call_tool(
            name="file_ops_safe",
            arguments={"operation": "append", "path": path, "content": content},
        )
    else:
        await call_tool(
            name="file_ops_safe",
            arguments={"operation": "write", "path": path, "content": content},
        )


source = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "read", "path": "notes/seed.md"},
)
source_text = _strip_read_output(source.output)
listing = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "list", "path": "notes"},
)
assembled = await assemble_context(
    instructions="Keep the response concise.",
    context_messages=[{"role": "system", "content": "Validation context"}],
    latest_user_message={"role": "user", "content": "Summarize the retrieved material."},
)
structured = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "read", "path": "notes/structured.md"},
)
parsed = await parse_markdown(value=STRUCTURED_NOTE_PLACEHOLDER)
task_listing = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "list", "path": "tasks"},
)
pending = await pending_files(operation="get", items=task_listing)
await pending_files(operation="complete", items=(pending.items[0],))

draft = await generate(
    prompt=(
        "Seed:\\n"
        + source_text
        + "\\n\\nListing:\\n"
        + listing.output
        + "\\n\\nAssembled messages:\\n"
        + str(len(assembled.messages))
    ),
    instructions="Return one short deterministic line.",
    model="test",
)

await _write_replace(
    "outputs/contract-success.md",
    source_text + f"\\nASSEMBLED={len(assembled.messages)}",
)
await _write_replace(
    "outputs/generate-success.md",
    draft.output,
)
await _write_replace(
    "outputs/parse-markdown.md",
    (
        f"name={parsed.frontmatter.get('name')}\\n"
        f"heading={parsed.sections[1].heading}\\n"
        f"code={parsed.code_blocks[0].language}\\n"
        f"image={parsed.images[0].src}"
    ),
)

await finish(status="completed", reason="all-helpers-exercised")
```
"""


AUTHORING_GENERATE_CACHE_DAILY_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Deterministic generate cache semantics workflow
---

## Run

```python
async def _write_replace(path, content):
    existing = await call_tool(
        name="file_ops_safe",
        arguments={"operation": "read", "path": path},
    )
    if existing.metadata.get("status") == "completed":
        await call_tool(
            name="file_ops_unsafe",
            arguments={"operation": "truncate", "path": path, "confirm_path": path},
        )
        await call_tool(
            name="file_ops_safe",
            arguments={"operation": "append", "path": path, "content": content},
        )
    else:
        await call_tool(
            name="file_ops_safe",
            arguments={"operation": "write", "path": path, "content": content},
        )

draft = await generate(
    prompt="Deterministic prompt",
    instructions="Return a short stable line.",
    model="test",
    cache="daily",
)

await _write_replace("outputs/generate-cache-status.md", f"status={draft.status}")
```
"""


STRUCTURED_NOTE = """---
name: Skill Example
description: Structured markdown sample
---

# Overview

General context.

## AI In Fiction

```python
print("hello")
```

![Example image](../images/test_image.jpg)
"""


AUTHORING_CONTRACT_SUCCESS_WORKFLOW = AUTHORING_CONTRACT_SUCCESS_WORKFLOW_TEMPLATE.replace(
    "STRUCTURED_NOTE_PLACEHOLDER",
    repr(STRUCTURED_NOTE),
)
