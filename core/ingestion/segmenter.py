"""
Chunking helpers for extracted content.
"""

from typing import List

from core.ingestion.models import ExtractedDocument, Chunk, RenderOptions


def default_segmenter(doc: ExtractedDocument, options: RenderOptions) -> List[Chunk]:
    """
    Basic segmenter placeholder: returns a single chunk of the whole document.
    """
    return [
        Chunk(
            id="chunk-0",
            order=0,
            text=doc.plain_text,
            title=doc.meta.get("title"),
            meta={"strategy_id": doc.strategy_id},
        )
    ]
