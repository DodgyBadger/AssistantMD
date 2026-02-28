"""Image importer for file-based sources."""

from __future__ import annotations

from pathlib import Path

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.registry import importer_registry


_EXT_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def load_image_from_path(path: Path) -> RawDocument:
    ext = path.suffix.lower()
    mime = _EXT_TO_MIME.get(ext)
    if mime is None:
        raise RuntimeError(f"Unsupported image extension: {ext}")

    return RawDocument(
        source_uri=str(path),
        kind=SourceKind.FILE,
        mime=mime,
        payload=path.read_bytes(),
        suggested_title=path.stem,
        meta={"filename": path.name},
    )


for extension in _EXT_TO_MIME:
    importer_registry.register(extension, load_image_from_path)
for mime_type in set(_EXT_TO_MIME.values()):
    importer_registry.register(mime_type, load_image_from_path)
