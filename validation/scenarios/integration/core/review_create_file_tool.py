"""Validate the reviewed create-file tool with real deferred execution."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.models.test import TestModel

from core.tools.review_create_file import ReviewCreateFileTool
from validation.core.base_scenario import BaseScenario


class ReviewCreateFileToolScenario(BaseScenario):
    """Validate reviewed file creation through Pydantic deferred tool approval."""

    async def test_scenario(self) -> None:
        vault = self.create_vault("ReviewCreateFileToolVault")
        await self.start_system()

        tool = ReviewCreateFileTool.get_tool(vault_path=str(vault))
        agent = Agent(
            model=TestModel(
                call_tools=["review_create_file"],
                custom_output_text="file reviewed",
            ),
            tools=[tool],
            output_type=[str, DeferredToolRequests],
        )

        first = await agent.run("Create a draft note.")
        assert isinstance(first.output, DeferredToolRequests)
        assert len(first.output.approvals) == 1
        call = first.output.approvals[0]
        assert call.tool_name == "review_create_file"
        assert not (vault / "Reviewed.md").exists(), "File should not exist before approval"

        approved = await agent.run(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={
                    call.tool_call_id: ToolApproved(
                        override_args={
                            "path": "Reviewed.md",
                            "content": "# Reviewed\n\nApproved content.\n",
                        }
                    )
                }
            ),
        )
        assert approved.output == "file reviewed"
        assert (vault / "Reviewed.md").read_text(encoding="utf-8") == (
            "# Reviewed\n\nApproved content.\n"
        )

        denied_first = await agent.run("Create another draft note.")
        denied_call = denied_first.output.approvals[0]
        denied = await agent.run(
            message_history=denied_first.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={
                    denied_call.tool_call_id: ToolDenied("Do not create this file.")
                }
            ),
        )
        assert denied.output == "file reviewed"
        assert not (vault / "a").exists(), "Denied create-file call should not write"

        await self.stop_system()
