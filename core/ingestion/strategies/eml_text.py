"""
Stub extractor for EML files.
"""

from __future__ import annotations

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry


def extract_eml_text(raw: RawDocument) -> ExtractedDocument:
    """
    TODO: Implement real EML parsing. For now, mark as unsupported content placeholder.
    """
    return ExtractedDocument(
        plain_text="EML ingestion stub: extraction not yet implemented.",
        mime=raw.mime or "message/rfc822",
        strategy_id="eml_stub",
        blocks=None,
        meta={"warning": "stub_extractor"},
    )


# Register extractor for EML MIME type
extractor_registry.register("message/rfc822", extract_eml_text)
extractor_registry.register("strategy:eml_stub", extract_eml_text)
