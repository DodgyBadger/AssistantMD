"""
Integration scenario for constrained-Python authoring host contract coverage.

Covers the currently implemented Monty host functions using deterministic model
execution and stable validation events rather than end-use wording.
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
        self.create_file(vault, "notes/extra.md", "EXTRA_CONTENT")
        self.copy_files("validation/templates/files/test_image.jpg", vault, "images")
        self.create_file(vault, "notes/structured.md", STRUCTURED_NOTE)

        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_contract_success.md",
            AUTHORING_CONTRACT_SUCCESS_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_cache_daily.md",
            AUTHORING_CACHE_DAILY_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_generate_cache_daily.md",
            AUTHORING_GENERATE_CACHE_DAILY_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_missing_file_scope.md",
            AUTHORING_MISSING_FILE_SCOPE_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_missing_file_output_scope.md",
            AUTHORING_MISSING_FILE_OUTPUT_SCOPE_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_missing_cache_scope.md",
            AUTHORING_MISSING_CACHE_SCOPE_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_missing_cache_output_scope.md",
            AUTHORING_MISSING_CACHE_OUTPUT_SCOPE_WORKFLOW,
        )
        self.create_file(
            vault,
            "AssistantMD/Workflows/authoring_missing_tool_scope.md",
            AUTHORING_MISSING_TOOL_SCOPE_WORKFLOW,
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
            name="authoring_retrieve_allowed",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "type": "file",
                "ref": "notes/seed.md",
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_retrieve_resolved",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "type": "file",
                "ref": "notes/seed.md",
                "item_count": 1,
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_retrieve_cache_resolved",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "type": "cache",
                "ref": "scratch/summary",
                "exists": True,
            },
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
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "input_count": 1,
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_generate_completed",
            expected={"workflow_id": "AuthoringContractVault/authoring_contract_success"},
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
            name="authoring_output_written",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "type": "file",
                "ref": "outputs/contract-success.md",
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_output_cache_written",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_contract_success",
                "type": "cache",
                "ref": "scratch/summary",
            },
        )
        self.assert_event_contains(
            events,
            name="authoring_monty_execution_completed",
            expected={"workflow_id": "AuthoringContractVault/authoring_contract_success"},
        )

        contract_output = vault / "outputs" / "contract-success.md"
        self.soft_assert(contract_output.exists(), "Expected contract success output file")
        if contract_output.exists():
            content = contract_output.read_text(encoding="utf-8")
            self.soft_assert("SEED_CONTENT" in content, "Expected retrieved file content in output")
            self.soft_assert("APPENDED_CACHE" in content, "Expected appended cache content in output")

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

        # Daily cache semantics should match existing cache behavior.
        self.set_date("2026-04-06")
        first_daily = await self.run_workflow(vault, "authoring_cache_daily")
        self.soft_assert_equal(first_daily.status, "completed", "First daily cache workflow run should succeed")
        daily_status = vault / "outputs" / "daily-status.md"
        self.soft_assert(
            daily_status.read_text(encoding="utf-8").strip() == "before=False; after=True",
            "First daily cache run should miss then populate cache",
        )

        second_daily = await self.run_workflow(vault, "authoring_cache_daily")
        self.soft_assert_equal(second_daily.status, "completed", "Second same-day cache run should succeed")
        self.soft_assert(
            daily_status.read_text(encoding="utf-8").strip() == "before=True; after=True",
            "Second same-day cache run should hit cache",
        )

        self.set_date("2026-04-07")
        checkpoint = self.event_checkpoint()
        third_daily = await self.run_workflow(vault, "authoring_cache_daily")
        self.soft_assert_equal(third_daily.status, "completed", "Next-day cache run should succeed")
        self.soft_assert(
            daily_status.read_text(encoding="utf-8").strip() == "before=False; after=True",
            "Next-day cache run should treat daily cache as expired",
        )
        daily_events = self.events_since(checkpoint)
        self.assert_event_contains(
            daily_events,
            name="authoring_retrieve_cache_resolved",
            expected={
                "workflow_id": "AuthoringContractVault/authoring_cache_daily",
                "ref": "scratch/daily",
                "exists": False,
            },
        )

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

        await self._assert_workflow_fails_with(
            vault,
            "authoring_missing_file_scope",
            "authoring.retrieve.file",
        )
        await self._assert_workflow_fails_with(
            vault,
            "authoring_missing_file_output_scope",
            "authoring.output.file",
        )
        await self._assert_workflow_fails_with(
            vault,
            "authoring_missing_cache_scope",
            "authoring.retrieve.cache",
        )
        await self._assert_workflow_fails_with(
            vault,
            "authoring_missing_cache_output_scope",
            "authoring.output.cache",
        )
        await self._assert_workflow_fails_with(
            vault,
            "authoring_missing_tool_scope",
            "authoring.tools",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    async def _assert_workflow_fails_with(
        self,
        vault: Path,
        workflow_name: str,
        expected_substring: str,
    ) -> None:
        checkpoint = self.event_checkpoint()
        result = await self.run_workflow(vault, workflow_name, expect_failure=True)
        self.soft_assert_equal(result.status, "failed", f"{workflow_name} should fail")
        self.soft_assert(
            expected_substring in (result.error_message or ""),
            f"{workflow_name} should include expected error text: {expected_substring}",
        )
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="authoring_monty_execution_failed",
            expected={
                "workflow_id": f"AuthoringContractVault/{workflow_name}",
            },
        )


AUTHORING_CONTRACT_SUCCESS_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Deterministic authoring contract success workflow
authoring.capabilities: [retrieve, generate, output, call_tool, parse_markdown]
authoring.retrieve.file: [notes/*.md, images/*]
authoring.retrieve.cache: [scratch/*]
authoring.output.file: [outputs/*.md, outputs/*.txt]
authoring.output.cache: [scratch/*]
authoring.tools: [file_ops_safe]
---

## Run

```python
source = await retrieve(type="file", ref="notes/seed.md")

await output(
    type="cache",
    ref="scratch/summary",
    data=source.items[0].content,
    options={"mode": "replace", "ttl": "daily"},
)
await output(
    type="cache",
    ref="scratch/summary",
    data="\\nAPPENDED_CACHE",
    options={"mode": "append", "ttl": "daily"},
)

cached = await retrieve(type="cache", ref="scratch/summary")
listing = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "list", "target": "notes"},
)
structured = await retrieve(type="file", ref="notes/structured.md")
parsed = await parse_markdown(value=structured.items[0])

draft = await generate(
    prompt=(
        "Seed:\\n"
        + cached.items[0].content
        + "\\n\\nListing:\\n"
        + listing.output
    ),
    inputs=source.items,
    instructions="Return one short deterministic line.",
    model="test",
)

await output(
    type="file",
    ref="outputs/contract-success.md",
    data=cached.items[0].content,
    options={"mode": "replace"},
)
await output(
    type="file",
    ref="outputs/generate-success.md",
    data=draft.output,
    options={"mode": "replace"},
)
await output(
    type="file",
    ref="outputs/parse-markdown.md",
    data=(
        f"name={parsed.frontmatter.get('name')}\\n"
        f"heading={parsed.sections[1].heading}\\n"
        f"code={parsed.code_blocks[0].language}\\n"
        f"image={parsed.images[0].src}"
    ),
    options={"mode": "replace"},
)
```
"""


AUTHORING_CACHE_DAILY_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Deterministic daily cache semantics workflow
authoring.capabilities: [retrieve, output]
authoring.retrieve.cache: [scratch/*]
authoring.output.file: [outputs/*.md]
authoring.output.cache: [scratch/*]
---

## Run

```python
cached_before = await retrieve(type="cache", ref="scratch/daily")
before = cached_before.items[0].exists

if not before:
    await output(
        type="cache",
        ref="scratch/daily",
        data="DAILY_CACHE",
        options={"mode": "replace", "ttl": "daily"},
    )

cached_after = await retrieve(type="cache", ref="scratch/daily")
after = cached_after.items[0].exists

await output(
    type="file",
    ref="outputs/daily-status.md",
    data=f"before={before}; after={after}",
    options={"mode": "replace"},
)
```
"""


AUTHORING_GENERATE_CACHE_DAILY_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Deterministic generate cache semantics workflow
authoring.capabilities: [generate, output]
authoring.output.file: [outputs/*.md]
---

## Run

```python
draft = await generate(
    prompt="Deterministic prompt",
    instructions="Return a short stable line.",
    model="test",
    cache="daily",
)

await output(
    type="file",
    ref="outputs/generate-cache-status.md",
    data=f"status={draft.status}",
    options={"mode": "replace"},
)
```
"""


AUTHORING_MISSING_FILE_SCOPE_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Missing retrieve.file scope
authoring.capabilities: [retrieve]
---

## Run

```python
await retrieve(type="file", ref="notes/seed.md")
```
"""


AUTHORING_MISSING_FILE_OUTPUT_SCOPE_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Missing output.file scope
authoring.capabilities: [output]
---

## Run

```python
await output(type="file", ref="outputs/missing-file-scope.md", data="x")
```
"""


AUTHORING_MISSING_CACHE_SCOPE_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Missing retrieve.cache scope
authoring.capabilities: [retrieve]
---

## Run

```python
await retrieve(type="cache", ref="scratch/missing")
```
"""


AUTHORING_MISSING_CACHE_OUTPUT_SCOPE_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Missing output.cache scope
authoring.capabilities: [output]
---

## Run

```python
await output(type="cache", ref="scratch/missing", data="x")
```
"""


AUTHORING_MISSING_TOOL_SCOPE_WORKFLOW = """---
workflow_engine: monty
enabled: false
description: Missing tool scope
authoring.capabilities: [call_tool]
---

## Run

```python
await call_tool(name="file_ops_safe", arguments={"operation": "list", "target": "notes"})
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
