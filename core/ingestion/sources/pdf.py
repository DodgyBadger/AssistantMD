"""
PDF importer for file-based sources.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.ingestion.models import RawDocument, SourceKind


def load_pdf_from_path(path: Path) -> RawDocument:
    data = path.read_bytes()
    title = path.stem
    return RawDocument(
        source_uri=str(path),
        kind=SourceKind.FILE,
        mime="application/pdf",
        payload=data,
        suggested_title=title,
        meta={"filename": path.name},
    )
