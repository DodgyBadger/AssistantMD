"""Validate the shared chat/Monty content import contract."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ToolReturn

from core.authoring.shared.tool_binding import resolve_tool_binding
from core.runtime.state import get_runtime_context
from core.tools.content_import import ContentImport
from core.web.models import WebFetchResult
from validation.core.base_scenario import BaseScenario


class ContentImportToolScenario(BaseScenario):
    """Prove singular/batch submission, status, preservation, and URL PDF routing."""

    async def test_scenario(self) -> None:
        vault = self.create_vault("ContentImportToolVault")
        local_pdf = vault / "Research" / "local.pdf"
        local_pdf.parent.mkdir(parents=True, exist_ok=True)
        local_pdf.write_bytes(self.make_pdf("Local content import validation"))

        await self.start_system()
        try:
            binding = resolve_tool_binding(["content_import"], vault_path=str(vault))
            self.soft_assert_equal(
                binding.tool_names(),
                ["content_import"],
                "content_import should bind for Monty direct tool calls",
            )

            tool = ContentImport.get_tool(vault_path=str(vault))
            submit = await tool.function(
                operation="submit",
                sources="Research/local.pdf",
            )
            self.soft_assert(
                isinstance(submit, ToolReturn),
                "submit should return a structured ToolReturn",
            )
            submit_items = (submit.metadata or {}).get("items") or []
            self.soft_assert_equal(len(submit_items), 1, "submit should create one job")
            local_job_id = submit_items[0].get("job_id") if submit_items else None
            self.soft_assert_equal(
                submit_items[0].get("status") if submit_items else None,
                "queued",
                "submit should return queued state",
            )

            await get_runtime_context().ingestion_worker.run_once()
            status = await tool.function(operation="status", job_ids=local_job_id)
            status_items = (status.metadata or {}).get("items") or []
            self.soft_assert_equal(
                status_items[0].get("status") if status_items else None,
                "completed",
                "status should expose terminal ingestion state",
            )
            self.soft_assert(
                local_pdf.exists(),
                "content_import must preserve a vault-relative source",
            )

            remote_url = "https://example.org/reports/remote.pdf"
            remote_pdf = self.make_pdf("Remote PDF content import validation")
            remote_submit = await tool.function(
                operation="submit",
                sources=[remote_url],
            )
            remote_items = (remote_submit.metadata or {}).get("items") or []
            remote_job_id = remote_items[0].get("job_id") if remote_items else None
            fetch_result = WebFetchResult(
                source_url=remote_url,
                effective_url=remote_url,
                status_code=200,
                headers={"content-type": "application/octet-stream"},
                body=remote_pdf,
                remote_ip="203.0.113.10",
            )
            with patch(
                "core.ingestion.sources.web.fetch_url_with_curl",
                return_value=fetch_result,
            ):
                await get_runtime_context().ingestion_worker.run_once()

            remote_status = await tool.function(
                operation="status",
                job_ids=[remote_job_id],
            )
            remote_status_items = (remote_status.metadata or {}).get("items") or []
            self.soft_assert_equal(
                remote_status_items[0].get("status") if remote_status_items else None,
                "completed",
                "PDF response bytes should route through PDF ingestion",
            )
            remote_outputs = (
                remote_status_items[0].get("outputs") if remote_status_items else []
            ) or []
            self.soft_assert_equal(
                len(remote_outputs), 1, "Remote PDF should create one markdown output"
            )
            if remote_outputs:
                remote_content = (vault / remote_outputs[0]).read_text(encoding="utf-8")
                self.soft_assert(
                    "Remote PDF content import validation" in remote_content,
                    "Remote PDF output should contain extracted text",
                )
                self.soft_assert(
                    f"source: {remote_url}" in remote_content,
                    "Remote output should preserve requested URL provenance",
                )

            invalid = await tool.function(
                operation="submit",
                sources="../outside.pdf",
            )
            self.soft_assert_equal(
                (invalid.metadata or {}).get("status"),
                "failed",
                "Traversal should return a structured tool failure",
            )
        finally:
            await self.stop_system()
            self.teardown_scenario()
        self.assert_no_failures()
