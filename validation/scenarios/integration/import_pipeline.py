"""
Validation scenario for the ingestion pipeline (file import flow).

Creates a small PDF in AssistantMD/Import, runs the import scan via API,
and asserts the rendered markdown output exists while the source file is removed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ImportPipelineScenario(BaseScenario):
    """Validate importing a PDF from AssistantMD/Import and ingesting a URL."""

    async def test_scenario(self):
        vault = self.create_vault("ImportPipelineVault")

        # Create a tiny PDF in the import folder
        pdf_bytes = self.make_pdf("Import validation\nLine two")
        import_path = vault / "AssistantMD" / "Import" / "sample.pdf"
        import_path.parent.mkdir(parents=True, exist_ok=True)
        import_path.write_bytes(pdf_bytes)

        await self.start_system()

        # Trigger import scan (processes immediately by default)
        response = self.call_api(
            "/api/import/scan",
            method="POST",
            data={"vault": vault.name, "queue_only": False},
        )
        assert response.status_code == 200, "Import scan should succeed"
        payload = response.json()
        jobs = payload.get("jobs_created") or []
        assert len(jobs) == 1, "One job should be created for the PDF"
        job = jobs[0]
        assert job.get("status") == "completed", "Job should complete inline"
        outputs = job.get("outputs") or []
        assert any(
            out.endswith("Imported/sample.md") for out in outputs
        ), "Output path should include Imported/sample.md"

        # Source file should be removed after successful import
        assert not import_path.exists(), "Source file should be cleaned up"

        # Validate the rendered markdown exists and contains the extracted text
        sample_path = vault / "Imported" / "sample.md"
        assert sample_path.exists(), "Expected Imported/sample.md to be created"
        sample_content = sample_path.read_text()
        assert "Import validation" in sample_content
        assert "mime: application/pdf" in sample_content

        # === URL INGEST ===
        url_response = self.call_api(
            "/api/import/url",
            method="POST",
            data={"vault": vault.name, "url": "https://example.com", "clean_html": True},
        )
        assert url_response.status_code == 200, "URL ingest should return 200"
        url_payload = url_response.json()
        assert url_payload.get("status") == "completed", (
            "URL ingest job should complete"
        )
        url_outputs = url_payload.get("outputs") or []
        assert len(url_outputs) > 0, "URL ingest should return at least one output path"
        # Verify the rendered file exists and contains expected markers
        for rel_path in url_outputs:
            output_path = vault / rel_path
            assert output_path.exists(), f"Expected {rel_path} to be created"
            output_content = output_path.read_text()
            assert "example" in output_content
            assert "mime: text/html" in output_content

        await self.stop_system()
        self.teardown_scenario()
