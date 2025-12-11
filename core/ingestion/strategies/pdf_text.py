"""
PyMuPDF-based text extractor for PDFs.
"""

from __future__ import annotations

from typing import Optional

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry


def extract_pdf_text(raw: RawDocument) -> ExtractedDocument:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF extraction") from exc

    doc = fitz.open(stream=raw.payload, filetype="pdf")
    texts = []
    for page in doc:
        texts.append(page.get_text("text"))
    plain_text = "\n\n".join(texts)

    return ExtractedDocument(
        plain_text=plain_text,
        mime="application/pdf",
        strategy_id="pdf_text",
        blocks=None,
        meta={"page_count": doc.page_count},
    )


# Register extractor for PDF MIME type
extractor_registry.register("application/pdf", extract_pdf_text)
extractor_registry.register("strategy:pdf_text", extract_pdf_text)
