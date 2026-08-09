"""Validate Mistral OCR URL transport and opt-in enrichment artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.ingestion.import_service import ContentImportService
from core.runtime.state import get_runtime_context
from validation.core.base_scenario import BaseScenario


class MistralOcrContractScenario(BaseScenario):
    """Validate direct PDF OCR without downloading the source through AssistantMD."""

    async def test_scenario(self):
        vault = self.create_vault("MistralOcrContractVault")
        await self.start_system()

        response = Mock(status_code=200)
        response.json.return_value = {
            "model": "mistral-ocr-4-0",
            "usage_info": {"pages_processed": 1},
            "pages": [
                {
                    "index": 0,
                    "markdown": "# Direct OCR",
                    "header": "Report header",
                    "blocks": [{"type": "title", "content": "Direct OCR"}],
                    "confidence_scores": {"average_page_confidence_score": 0.99},
                }
            ],
        }

        with (
            patch(
                "core.ingestion.service.resolve_public_url",
                return_value=("example.org", ["93.184.216.34"]),
            ),
            patch("core.ingestion.service.secret_has_value", return_value=True),
            patch("core.ingestion.capabilities.secret_has_value", return_value=True),
            patch(
                "core.ingestion.strategies.mistral_ocr_common.get_secret_value",
                return_value="test-key",
            ),
            patch(
                "core.ingestion.strategies.mistral_ocr_common.requests.post",
                return_value=response,
            ) as post,
        ):
            metadata_response = self.call_api("/api/metadata")
            pdf_ocr_capability = (
                metadata_response.json()
                .get("ingestion_capabilities", {})
                .get("pdf_ocr", {})
            )
            self.soft_assert_equal(
                pdf_ocr_capability.get("available"),
                True,
                "Metadata should expose backend-derived PDF OCR availability",
            )
            self.soft_assert(
                "blocks" in (pdf_ocr_capability.get("features") or []),
                "Metadata should expose supported PDF OCR enrichments",
            )
            self.soft_assert_equal(
                pdf_ocr_capability.get("default_order"),
                ["pdf_text", "pdf_ocr"],
                "Metadata should expose the configured PDF strategy order",
            )
            service = ContentImportService(str(vault))
            submitted = service.submit(
                sources="https://example.org/report.pdf",
                options={
                    "strategies": ["pdf_ocr"],
                    "include_ocr_blocks": True,
                    "extract_ocr_header": True,
                    "ocr_confidence": "page",
                },
            )
            await get_runtime_context().ingestion_worker.run_once()
            result = service.status(job_ids=submitted[0].job_id)[0]

        self.soft_assert_equal(result.status, "completed", "OCR job should complete")
        self.soft_assert_equal(
            result.selected_strategy, "pdf_ocr", "PDF OCR should be selected"
        )
        self.soft_assert_equal(
            result.selected_provider, "mistral", "Provider should be recorded"
        )
        request_payload = json.loads(post.call_args.kwargs["data"])
        self.soft_assert_equal(
            request_payload["document"],
            {
                "type": "document_url",
                "document_url": "https://example.org/report.pdf",
            },
            "Public OCR-only PDF URLs should be delivered directly to Mistral",
        )
        self.soft_assert_equal(
            request_payload.get("include_blocks"), True, "Blocks should be opt-in"
        )
        self.soft_assert_equal(
            request_payload.get("extract_header"),
            True,
            "Header extraction should be opt-in",
        )
        self.soft_assert_equal(
            request_payload.get("confidence_scores_granularity"),
            "page",
            "Confidence granularity should be forwarded",
        )
        outputs = result.outputs
        self.soft_assert(
            any(path.endswith("/ocr.json") for path in outputs),
            "Requested structured OCR data should be retained as an asset",
        )

        await self.stop_system()
        self.teardown_scenario()
