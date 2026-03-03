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
    """Validate importing a PDF from AssistantMD/Import."""

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
        assert len(outputs) > 0, "Import scan should return at least one output path"
        sample_rel_path = outputs[0]
        assert sample_rel_path.endswith(".md"), "Import output should be markdown"
        assert sample_rel_path.startswith("Imported/"), "Import output should be under Imported/"

        # Source file should be removed after successful import
        assert not import_path.exists(), "Source file should be cleaned up"

        # Validate the rendered markdown exists and contains the extracted text
        sample_path = vault / sample_rel_path
        assert sample_path.exists(), f"Expected {sample_rel_path} to be created"
        sample_content = sample_path.read_text()
        assert "Import validation" in sample_content
        assert "mime: application/pdf" in sample_content

        await self.stop_system()
        self.teardown_scenario()
