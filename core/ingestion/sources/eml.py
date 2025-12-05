"""
EML importer for file-based sources.
"""

from __future__ import annotations

from pathlib import Path

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.registry import importer_registry


def load_eml_from_path(path: Path) -> RawDocument:
    data = path.read_bytes()
    title = path.stem
    return RawDocument(
        source_uri=str(path),
        kind=SourceKind.FILE,
        mime="message/rfc822",
        payload=data,
        suggested_title=title,
        meta={"filename": path.name},
    )


# Register importer for EML by extension and MIME type
importer_registry.register(".eml", load_eml_from_path)
importer_registry.register("message/rfc822", load_eml_from_path)
