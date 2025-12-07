"""
Validation scenario for the ingestion pipeline (file import flow).

Creates a small PDF in AssistantMD/import, runs the import scan via API,
and asserts the rendered markdown output exists while the source file is removed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ImportPipelineScenario(BaseScenario):
    """Validate importing a PDF from AssistantMD/import and ingesting a URL."""

    async def test_scenario(self):
        vault = self.create_vault("ImportPipelineVault")

        # Create a tiny PDF in the import folder
        pdf_bytes = self.make_pdf("Import validation\nLine two")
        import_path = vault / "AssistantMD" / "import" / "sample.pdf"
        import_path.parent.mkdir(parents=True, exist_ok=True)
        import_path.write_bytes(pdf_bytes)

        await self.start_system()

        # Trigger import scan (processes immediately by default)
        response = self.call_api(
            "/api/import/scan",
            method="POST",
            data={"vault": vault.name, "queue_only": False},
        )
        self.expect_equals(response.status_code, 200, "Import scan should succeed")
        payload = response.json()
        jobs = payload.get("jobs_created") or []
        self.expect_equals(len(jobs), 1, "One job should be created for the PDF")
        job = jobs[0]
        self.expect_equals(job.get("status"), "completed", "Job should complete inline")
        outputs = job.get("outputs") or []
        self.expect_equals(
            any(out.endswith("Imported/sample.md") for out in outputs),
            True,
            "Output path should include Imported/sample.md",
        )

        # Source file should be removed after successful import
        self.expect_equals(import_path.exists(), False, "Source file should be cleaned up")

        # Validate the rendered markdown exists and contains the extracted text
        self.expect_file_created(vault, "Imported/sample.md")
        self.expect_file_contains(vault, "Imported/sample.md", "Import validation")
        self.expect_file_contains(vault, "Imported/sample.md", "mime: application/pdf")

        # === URL INGEST ===
        url_response = self.call_api(
            "/api/import/url",
            method="POST",
            data={"vault": vault.name, "url": "https://example.com", "clean_html": True},
        )
        self.expect_equals(url_response.status_code, 200, "URL ingest should return 200")
        url_payload = url_response.json()
        self.expect_equals(
            url_payload.get("status"), "completed", "URL ingest job should complete"
        )
        url_outputs = url_payload.get("outputs") or []
        self.expect_equals(
            len(url_outputs) > 0,
            True,
            "URL ingest should return at least one output path",
        )
        # Verify the rendered file exists and contains expected markers
        for rel_path in url_outputs:
            self.expect_file_created(vault, rel_path)
            self.expect_file_contains(vault, rel_path, "example")
            self.expect_file_contains(vault, rel_path, "mime: text/html")

        await self.stop_system()
        self.teardown_scenario()
