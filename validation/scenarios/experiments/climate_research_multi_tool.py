"""
Climate Research Multi-Tool scenario - tests LLM tool selection in comprehensive workflow.

This scenario gives the LLM access to all three tools (web_search, tavily_extract, tavily_crawl)
at each step and lets it choose the most appropriate tool for each task.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# No more path isolation monkey patches needed! CoreServices handles clean dependency injection.

from validation.core.base_scenario import BaseScenario


class ClimateResearchMultiToolScenario(BaseScenario):
    """Test LLM tool selection in multi-tool climate research workflow."""
    
    async def test_scenario(self):
        """Execute multi-step climate research workflow with flexible tool selection."""

        # === SETUP ===
        vault = self.create_vault("KnowledgeVault")

        # Create the multi-tool climate research workflow
        self.create_file(vault, "AssistantMD/Workflows/climate-research-multi-tool.md", CLIMATE_RESEARCH_MULTI_TOOL_WORKFLOW)

        # === SYSTEM STARTUP VALIDATION ===
        await self.start_system()

        # Validate system startup
        assert "KnowledgeVault" in self.get_discovered_vaults(), "Vault not discovered"
        workflows = self.get_loaded_workflows()
        assert any(
            cfg.global_id == "KnowledgeVault/climate-research-multi-tool"
            for cfg in workflows
        ), "Workflow not loaded"
        jobs = self.get_scheduler_jobs()
        assert any(
            job.job_id == "KnowledgeVault__climate-research-multi-tool" for job in jobs
        ), "Scheduler job not created"

        # === COMPREHENSIVE RESEARCH EXECUTION ===
        self.set_date("2025-01-20")  # Monday

        # Trigger the multi-step research workflow with LLM tool selection
        self._log_timeline("🌍 Starting multi-tool climate change research workflow...")
        await self.trigger_job(vault, "climate-research-multi-tool")

        # === ASSERTIONS ===
        assert len(self.get_job_executions(vault, "climate-research-multi-tool")) > 0, (
            "No executions recorded for KnowledgeVault/climate-research-multi-tool"
        )

        # Verify all research phases created their output files
        for rel_path in [
            "climate-research/01-overview.md",
            "climate-research/02-science-foundation.md",
            "climate-research/03-solutions.md",
            "climate-research/05-knowledge-base.md",
        ]:
            output_path = vault / rel_path
            assert output_path.exists(), f"Expected {rel_path} to be created"
            assert output_path.stat().st_size > 0, f"{rel_path} is empty"

        self._log_timeline("✅ Multi-tool climate research workflow completed successfully")

        # Clean up
        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

CLIMATE_RESEARCH_MULTI_TOOL_WORKFLOW = """---
schedule: once: 2030-01-01 09:00
workflow_engine: step
enabled: true
description: Climate research workflow with all tools available - let LLM choose best approach
---

## INSTRUCTIONS
You are a comprehensive climate research workflow helping build a detailed knowledge base about climate change. Use the tools provided to gather, analyze, and structure information about climate science, impacts, and solutions. You have access to web search, content extraction, and web crawling tools - choose the most appropriate tool for each task. Provide links to back up your analysis and for further research.

## OVERVIEW_RESEARCH
@model gemini
@tools web_search, tavily_extract, tavily_crawl
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output file:climate-research/01-overview

Search for current climate science consensus and overview information:
- Find the latest IPCC report key findings and summary
- Research current global climate impacts and trends
- Look for reputable climate science explainers from NASA, NOAA, or scientific organizations

Use whichever tool(s) work best to get authoritative, recent sources that provide a solid foundation for deeper research.

## SCIENTIFIC_FOUNDATION
@model gemini
@tools web_search, tavily_extract, tavily_crawl
@input file:climate-research/01-overview
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output file:climate-research/02-science-foundation

Based on the overview research, gather detailed content from the most promising authoritative climate science sources identified:
- Get key sections from NASA climate science pages
- Get IPCC report summaries and key findings
- Get NOAA climate.gov explanations of climate mechanisms
- Get peer-reviewed research summaries on climate impacts

Choose the most effective tool for each source - extract for single pages, crawl for comprehensive site exploration, or search for finding additional sources. Build on the overview findings to provide comprehensive scientific foundation with proper source attribution.

## SOLUTIONS_ANALYSIS
@model gemini
@tools web_search, tavily_extract, tavily_crawl
@input file:climate-research/01-overview
@input file:climate-research/02-science-foundation
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output file:climate-research/03-solutions

Using the scientific foundation established in previous steps, comprehensively research climate solutions:
- Research climate.gov for detailed climate solutions information
- Research reputable environmental organization sites for solution databases
- Focus on solutions that address the specific impacts identified in earlier research

Use the most appropriate tools for gathering detailed information about:
- Technology-based solutions relevant to the science covered
- Policy approaches and their effectiveness
- Individual and community-level actions
- Economic aspects of climate solutions

If crawling fails due to site protection, fall back to targeted extraction or search approaches.

## KNOWLEDGE_SUMMARY
@model gemini
@tools web_search, tavily_extract, tavily_crawl
@input file:climate-research/01-overview
@input file:climate-research/02-science-foundation
@input file:climate-research/03-solutions
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output file:climate-research/05-knowledge-base

Create the final comprehensive climate change knowledge base by synthesizing all research phases:
- Integrate findings from overview, scientific foundation, solutions, and analysis
- Create an interconnected overview showing relationships between science, impacts, and solutions
- Provide clear pathways for continued learning and action based on the research
- Structure as a comprehensive knowledge base suitable for ongoing reference and expansion
- Use tools to fill any gaps identified during synthesis

This represents the culmination of a systematic climate change research project with flexible tool usage.
"""
