"""
DOCX extractor using markitdown for markdown conversion.
"""

from __future__ import annotations

import io

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry

try:
    from markitdown import MarkItDown
except ImportError as exc:
    MarkItDown = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def extract_docx_text(raw: RawDocument) -> ExtractedDocument:
    """
    Convert DOCX to markdown using markitdown.
    """
    if MarkItDown is None:
        raise RuntimeError(f"markitdown is required for DOCX extraction: {_IMPORT_ERROR}")

    md = MarkItDown()
    source = raw.payload
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    elif isinstance(source, str):
        source = io.BytesIO(source.encode("utf-8"))

    result = md.convert(source)
    text = result.text_content or ""
    if not text.strip():
        raise RuntimeError("DOCX extraction produced no content")

    warnings = []
    if hasattr(result, "attachment_links") and result.attachment_links:
        warnings.append("attachments:dropped")

    return ExtractedDocument(
        plain_text=text.strip(),
        mime=raw.mime or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        strategy_id="docx_text",
        blocks=None,
        meta={"warnings": warnings} if warnings else {},
    )


# Register extractor for DOCX MIME type
extractor_registry.register(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    extract_docx_text,
)
extractor_registry.register("strategy:docx_text", extract_docx_text)
