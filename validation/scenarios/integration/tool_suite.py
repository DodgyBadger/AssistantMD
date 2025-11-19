"""
Integration scenario that exercises every configured tool using TestModel.

Runs a multi-step workflow where each step enables a single tool so we can
confirm tool wiring without external API calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ToolSuiteScenario(BaseScenario):
    """Validate that every tool can be invoked successfully with TestModel."""

    async def test_scenario(self):
        vault = self.create_vault("ToolSuiteVault")

        # Seed workflow that contains one step per tool
        self.create_file(vault,"AssistantMD/Workflows/tool_suite.md",TOOL_SUITE_WORKFLOW)

        await self.start_system()

        self.expect_vault_discovered("ToolSuiteVault")
        self.expect_workflow_loaded("ToolSuiteVault", "tool_suite")

        # Run with deterministic date for pattern placeholders if used later
        self.set_date("2025-01-06")  # Monday

        result = await self.run_workflow(vault, "tool_suite")
        self.expect_equals(result.status, "completed", "Tool suite workflow should finish successfully")

        expected_outputs = [
            "tool-outputs/documentation-access.md",
            "tool-outputs/file-ops-safe.md",
            "tool-outputs/file-ops-unsafe.md",
            "tool-outputs/web-search-duckduckgo.md",
            "tool-outputs/web-search-tavily.md",
            "tool-outputs/tavily-extract.md",
            "tool-outputs/tavily-crawl.md",
            "tool-outputs/code-execution.md",
        ]

        for relative_path in expected_outputs:
            self.expect_file_created(vault, relative_path)

        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

TOOL_SUITE_WORKFLOW = """
---
workflow_engine: step
enabled: false
description: Validation workflow that exercises every available tool with the TestModel.
---

## STEP1_DOCUMENTATION
@model gpt-mini
@tools documentation_access
@output-file tool-outputs/documentation-access

Provide a quick summary of the documentation home page using the documentation access tool.

## STEP2_FILE_OPS_SAFE
@model gpt-mini
@tools file_ops_safe
@output-file tool-outputs/file-ops-safe

Call the safe file operations tool with any operation so we capture the tool output.

## STEP3_FILE_OPS_UNSAFE
@model gpt-mini
@tools file_ops_unsafe
@output-file tool-outputs/file-ops-unsafe

Invoke the unsafe file operations tool once to record its response. Do not rely on any existing files.

## STEP4_WEB_SEARCH_DUCKDUCKGO
@model gpt-mini
@tools web_search_duckduckgo
@output-file tool-outputs/web-search-duckduckgo

Use the DuckDuckGo search backend to look up a topic of your choice.

## STEP5_WEB_SEARCH_TAVILY
@model gpt-mini
@tools web_search_tavily
@output-file tool-outputs/web-search-tavily

Use the Tavily search backend to look up a topic of your choice.

## STEP6_TAVILY_EXTRACT
@model gpt-mini
@tools tavily_extract
@output-file tool-outputs/tavily-extract

Call the Tavily extract tool on any URL so we capture the tool output.

## STEP7_TAVILY_CRAWL
@model gpt-mini
@tools tavily_crawl
@output-file tool-outputs/tavily-crawl

Call the Tavily crawl tool on any URL so we capture the tool output.

## STEP8_CODE_EXECUTION
@model gpt-mini
@tools code_execution
@output-file tool-outputs/code-execution

Run the code execution tool with a short code sample so we capture the tool output.

"""