#!/usr/bin/env python3
"""
Helper utility for exporting changelog data for releases.

Usage:
    python scripts/export_changelog.py \
        --output changelog.md \
        --latest-output release-notes.md
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import changelog


def format_entry(entry: dict) -> Iterable[str]:
    """Render a single changelog entry as markdown lines."""
    header = f"## {entry['date']} - {entry['title']}"
    if entry.get("phases"):
        header += f" ({entry['phases']})"

    yield header
    if entry.get("category"):
        yield f"_Category_: `{entry['category']}`"
    yield ""
    yield entry["content"].strip()


def write_latest_entry(path: Path, limit: int = 1):
    """Write the latest changelog entry (or entries) to the given path."""
    entries = changelog.get_entries(limit=limit)
    if not entries:
        path.write_text("No changelog entries available.\n", encoding="utf-8")
        return

    lines: list[str] = []
    for entry in reversed(entries):
        lines.extend(format_entry(entry))
        lines.append("\n---\n")

    content = "\n".join(lines).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Export changelog data for releases.")
    parser.add_argument(
        "--output",
        default="changelog.md",
        help="Path for the full changelog export (default: changelog.md).",
    )
    parser.add_argument(
        "--latest-output",
        help="Optional path for exporting the most recent entry excerpt.",
    )
    parser.add_argument(
        "--latest-count",
        type=int,
        default=1,
        help="Number of latest entries to include in the excerpt (default: 1).",
    )
    args = parser.parse_args()

    full_output = Path(args.output)
    full_output.parent.mkdir(parents=True, exist_ok=True)
    changelog.export_markdown(str(full_output))

    if args.latest_output:
        latest_path = Path(args.latest_output)
        write_latest_entry(latest_path, limit=max(1, args.latest_count))


if __name__ == "__main__":
    main()
