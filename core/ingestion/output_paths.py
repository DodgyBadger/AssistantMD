from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportOutputPaths:
    rel_dir: str
    base_name: str
    job_dir: str
    markdown_path: str


def resolve_import_output_paths(
    *,
    path_pattern: str | None,
    relative_dir: str,
    source_filename: str | None,
    title: str | None,
) -> ImportOutputPaths:
    base_dir = path_pattern or "Imported/"
    rel_dir = base_dir.rstrip("/")
    if relative_dir:
        rel_dir = os.path.join(rel_dir, relative_dir.strip("/"))

    filename = None
    if source_filename:
        filename = Path(source_filename).stem
    if not filename:
        filename = title or "import"

    if source_filename and str(source_filename).startswith("http"):
        filename = _slugify(filename)
    else:
        filename = filename.replace("/", "_").replace("\\", "_").strip() or "import"

    job_dir = os.path.join(rel_dir, filename).lstrip("/")
    markdown_path = os.path.join(job_dir, f"{filename}.md").lstrip("/")
    return ImportOutputPaths(
        rel_dir=rel_dir,
        base_name=filename,
        job_dir=job_dir,
        markdown_path=markdown_path,
    )


def _slugify(name: str) -> str:
    allowed = []
    for ch in name.lower():
        if ch.isalnum():
            allowed.append(ch)
        elif ch in (" ", "-", "_"):
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    return slug or "import"
