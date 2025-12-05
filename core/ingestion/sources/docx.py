"""
DOCX importer for file-based sources.
"""

from __future__ import annotations

from pathlib import Path

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.registry import importer_registry


def load_docx_from_path(path: Path) -> RawDocument:
    data = path.read_bytes()
    title = path.stem
    return RawDocument(
        source_uri=str(path),
        kind=SourceKind.FILE,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        payload=data,
        suggested_title=title,
        meta={"filename": path.name},
    )


# Register importer for DOCX by extension and MIME type
importer_registry.register(".docx", load_docx_from_path)
importer_registry.register(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    load_docx_from_path,
)
