"""
Fallback DOCX extractor stub (kept for registry completeness if markitdown is missing).
"""

from __future__ import annotations

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry


def extract_docx_stub(raw: RawDocument) -> ExtractedDocument:
    return ExtractedDocument(
        plain_text="DOCX extraction placeholder: markitdown not available.",
        mime=raw.mime or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        strategy_id="docx_stub",
        blocks=None,
        meta={"warnings": ["docx_stub:missing_markitdown"]},
    )


extractor_registry.register(
    "strategy:docx_stub",
    extract_docx_stub,
)
