"""
Office document extractor using markitdown for markdown conversion (docx/pptx/xlsx/etc.).
"""

from __future__ import annotations

import io

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry

try:
    from markitdown import MarkItDown, StreamInfo
except ImportError as exc:
    MarkItDown = None  # type: ignore[assignment]
    StreamInfo = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def extract_markitdown(raw: RawDocument) -> ExtractedDocument:
    """
    Convert Office documents to markdown using markitdown.
    """
    if MarkItDown is None or StreamInfo is None:
        raise RuntimeError(f"markitdown is required for Office extraction: {_IMPORT_ERROR}")

    md = MarkItDown()
    source = raw.payload
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    elif isinstance(source, str):
        source = io.BytesIO(source.encode("utf-8"))

    filename = raw.meta.get("filename") if isinstance(raw.meta, dict) else None
    stream_info = StreamInfo(filename=filename) if filename else None
    result = md.convert(source, stream_info=stream_info)
    text = result.text_content or ""
    if not text.strip():
        raise RuntimeError("markitdown extraction produced no content")

    warnings = []
    if hasattr(result, "attachment_links") and result.attachment_links:
        warnings.append("attachments:dropped")

    return ExtractedDocument(
        plain_text=text.strip(),
        mime=raw.mime or "application/octet-stream",
        strategy_id="markitdown",
        blocks=None,
        meta={"warnings": warnings} if warnings else {},
    )


# Register extractor for Office MIME types and strategy id
extractor_registry.register(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    extract_markitdown,
)
extractor_registry.register(
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    extract_markitdown,
)
extractor_registry.register(
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    extract_markitdown,
)
extractor_registry.register("strategy:markitdown", extract_markitdown)
