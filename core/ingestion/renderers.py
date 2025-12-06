"""
Render extracted chunks to markdown artifacts.
"""

from typing import List
from datetime import datetime
import os
from pathlib import Path

from core.ingestion.models import ExtractedDocument, Chunk, RenderOptions
from core.runtime.paths import get_data_root


def default_renderer(doc: ExtractedDocument, chunks: List[Chunk], options: RenderOptions) -> List[dict]:
    """
    Placeholder renderer that returns structured artifacts ready for storage.
    """
    slug = options.title or options.source_filename or "import"
    slug = _slugify(slug)
    base = options.path_pattern or "Imported/"
    rel_dir = base.rstrip("/") + "/" + (options.relative_dir or "")
    rel_dir = rel_dir.lstrip("/")
    rel_dir = rel_dir + slug + "/"
    rel_path = os.path.join(rel_dir, "index.md")

    display_source_path = None
    if options.source_filename:
        try:
            data_root = Path(get_data_root()).resolve()
            source_path = Path(options.source_filename).resolve()
            if options.vault:
                vault_root = (data_root / options.vault).resolve()
                if str(source_path).startswith(str(vault_root)):
                    display_source_path = str(source_path.relative_to(vault_root))
            if display_source_path is None and str(source_path).startswith(str(data_root)):
                display_source_path = str(source_path.relative_to(data_root))
        except Exception:
            display_source_path = options.source_filename
        else:
            if display_source_path is None:
                display_source_path = options.source_filename

    frontmatter = {
        "source": os.path.basename(options.source_filename or ""),
        "source_path": display_source_path,
        "mime": doc.mime,
        "strategy": doc.strategy_id,
        "fetched_at": datetime.utcnow().isoformat(),
        "chunk_count": len(chunks),
    }

    # Record any attachments the extractor saw but intentionally dropped to keep vault markdown-only
    attachments = doc.meta.get("attachments") if isinstance(doc.meta, dict) else None
    if attachments:
        # Only store the names/identifiers to avoid embedding binary references
        frontmatter["dropped_attachments"] = [str(att) for att in attachments]
    warnings = doc.meta.get("warnings") if isinstance(doc.meta, dict) else None
    if warnings:
        frontmatter["warnings"] = [str(w) for w in warnings]

    body_lines = []
    for chunk in chunks:
        body_lines.append(chunk.text)

    content = "---\n"
    for key, val in frontmatter.items():
        if val is not None:
            content += f"{key}: {val}\n"
    content += "---\n\n"
    content += "\n\n".join(body_lines)

    return [
        {
            "path": rel_path,
            "content": content,
            "meta": frontmatter,
        }
    ]


def _slugify(name: str) -> str:
    allowed = []
    for ch in name.lower():
        if ch.isalnum():
            allowed.append(ch)
        elif ch in (" ", "-", "_"):
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    return slug or "import"
