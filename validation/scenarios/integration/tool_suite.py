"""
Integration scenario that exercises every configured tool with a lightweight model.

Runs a multi-step workflow where each step enables a single tool with deterministic,
small inputs to keep runtime and costs low.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ToolSuiteScenario(BaseScenario):
    """Validate that every tool can be invoked successfully with a lightweight model."""

    async def test_scenario(self):
        vault = self.create_vault("ToolSuiteVault")

        # Seed workflow that contains one step per tool
        self.create_file(vault,"AssistantMD/Workflows/tool_suite.md",TOOL_SUITE_WORKFLOW)

        await self.start_system()

        assert "ToolSuiteVault" in self.get_discovered_vaults(), "Vault not discovered"
        workflows = self.get_loaded_workflows()
        assert any(
            cfg.global_id == "ToolSuiteVault/tool_suite" for cfg in workflows
        ), "Workflow not loaded"

        # Run with deterministic date for pattern placeholders if used later
        self.set_date("2025-01-06")  # Monday

        result = await self.run_workflow(vault, "tool_suite")
        assert result.status == "completed", (
            "Tool suite workflow should finish successfully"
        )

        expected_outputs = [
            "tool-outputs/documentation-access.md",
            "tool-outputs/file-ops-safe.md",
            "tool-outputs/file-ops-unsafe.md",
            "tool-outputs/web-search-duckduckgo.md",
            "tool-outputs/code-execution.md",
            "tool-outputs/import-url.md"
        ]

        for relative_path in expected_outputs:
            output_path = vault / relative_path
            assert output_path.exists(), f"Expected {relative_path} to be created"
            assert output_path.stat().st_size > 0, f"{relative_path} is empty"

        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

TOOL_SUITE_WORKFLOW = """
---
workflow_engine: step
enabled: false
description: Validation workflow that exercises every available tool with a lightweight model.
---

## DOCUMENTATION
@model gpt-nano
@tools documentation_access
@output-file tool-outputs/documentation-access

Summarize the documentation home page in 3 bullet points.

## FILE_OPS_SAFE
@model gpt-nano
@tools file_ops_safe
@output-file tool-outputs/file-ops-safe

Use the safe file operations tool to list the root of the vault and report the first entry found.

## FILE_OPS_UNSAFE
@model gpt-nano
@tools file_ops_unsafe
@output-file tool-outputs/file-ops-unsafe

Use the unsafe file operations tool to create a throwaway file named tmp/unsafe-test.txt with the content 'ok', then report success. Do not touch any other files.

## WEB_SEARCH_DUCKDUCKGO
@model gpt-nano
@tools web_search_duckduckgo
@output-file tool-outputs/web-search-duckduckgo

Search DuckDuckGo for "pydantic ai release" and return the top results in a short list.

## IMPORT_URL
@model gpt-nano
@tools import_url
@output-file tool-outputs/import-url

Import the webpage https://example.com.

## CODE_EXECUTION
@model gpt-nano
@tools code_execution
@output-file tool-outputs/code-execution

Run a tiny Python snippet that prints 2+2.

"""
