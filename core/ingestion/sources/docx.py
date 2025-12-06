"""
Office document importer for file-based sources (docx, pptx, xlsx).
"""

from __future__ import annotations

from pathlib import Path

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.registry import importer_registry


def load_doc_from_path(path: Path, mime: str) -> RawDocument:
    data = path.read_bytes()
    title = path.stem
    return RawDocument(
        source_uri=str(path),
        kind=SourceKind.FILE,
        mime=mime,
        payload=data,
        suggested_title=title,
        meta={"filename": path.name},
    )


def load_docx_from_path(path: Path) -> RawDocument:
    return load_doc_from_path(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def load_pptx_from_path(path: Path) -> RawDocument:
    return load_doc_from_path(path, "application/vnd.openxmlformats-officedocument.presentationml.presentation")


def load_xlsx_from_path(path: Path) -> RawDocument:
    return load_doc_from_path(path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Register importer for Office by extension and MIME type
importer_registry.register(".docx", load_docx_from_path)
importer_registry.register("application/vnd.openxmlformats-officedocument.wordprocessingml.document", load_docx_from_path)

importer_registry.register(".pptx", load_pptx_from_path)
importer_registry.register("application/vnd.openxmlformats-officedocument.presentationml.presentation", load_pptx_from_path)

importer_registry.register(".xlsx", load_xlsx_from_path)
importer_registry.register("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", load_xlsx_from_path)
