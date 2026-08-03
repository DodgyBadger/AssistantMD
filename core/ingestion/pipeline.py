"""
Orchestrates ingestion jobs through importer, extractor, renderer, and storage.
"""

from collections.abc import Callable
from typing import Any

from core.ingestion.models import ExtractedDocument, RawDocument, RenderOptions


def run_pipeline(
    raw: RawDocument,
    extractor_fn: Callable[[RawDocument], ExtractedDocument],
    renderer_fn: Callable[[ExtractedDocument, RenderOptions], Any],
    storage_fn: Callable[[Any], list[str]],
    render_options: RenderOptions,
) -> list[str]:
    """
    Run ingestion pipeline for a single document.

    Returns list of written artifact paths.
    """
    extracted: ExtractedDocument = extractor_fn(raw)
    return storage_fn(renderer_fn(extracted, render_options))
