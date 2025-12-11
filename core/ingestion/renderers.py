"""
Render extracted chunks to markdown artifacts.
"""

from typing import List
from datetime import datetime
import os
from pathlib import Path

from core.ingestion.models import ExtractedDocument, RenderOptions
from core.runtime.paths import get_data_root


def default_renderer(doc: ExtractedDocument, options: RenderOptions) -> List[dict]:
    """
    Render a single markdown artifact for the extracted document.
    """
    base_dir = options.path_pattern or "Imported/"
    rel_dir = base_dir.rstrip("/")
    if options.relative_dir:
        rel_dir = os.path.join(rel_dir, options.relative_dir.strip("/"))

    # Prefer original filename when available; otherwise derive from title/URL
    filename = None
    if options.source_filename:
        filename = Path(options.source_filename).stem
    if not filename:
        filename = options.title or "import"

    if options.source_filename and options.source_filename.startswith("http"):
        filename = _slugify(filename)
    else:
        # Keep file-like names but strip path separators
        filename = filename.replace("/", "_").replace("\\", "_").strip() or "import"

    rel_path = os.path.join(rel_dir, f"{filename}.md").lstrip("/")

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
    }

    # Record any attachments the extractor saw but intentionally dropped to keep vault markdown-only
    attachments = doc.meta.get("attachments") if isinstance(doc.meta, dict) else None
    if attachments:
        # Only store the names/identifiers to avoid embedding binary references
        frontmatter["dropped_attachments"] = [str(att) for att in attachments]
    warnings = doc.meta.get("warnings") if isinstance(doc.meta, dict) else None
    if warnings:
        frontmatter["warnings"] = [str(w) for w in warnings]

    content = "---\n"
    for key, val in frontmatter.items():
        if val is not None:
            content += f"{key}: {val}\n"
    content += "---\n\n"
    content += doc.plain_text or ""

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
