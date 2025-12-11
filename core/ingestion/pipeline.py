"""
Orchestrates ingestion jobs through importer, extractor, renderer, and storage.
"""

from typing import Any

from core.ingestion.models import RawDocument, ExtractedDocument, RenderOptions


def run_pipeline(
    raw: RawDocument,
    extractor_fn: Any,
    renderer_fn: Any,
    storage_fn: Any,
    render_options: RenderOptions,
) -> list[str]:
    """
    Run ingestion pipeline for a single document.

    Returns list of written artifact paths.
    """
    extracted: ExtractedDocument = extractor_fn(raw)
    return storage_fn(renderer_fn(extracted, render_options))
