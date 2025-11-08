#!/usr/bin/env python3
"""
Populate the lint_warnings column in the review matrix using Ruff output.

The script runs ``ruff check --output-format json`` (via uvx) to gather lint
diagnostics, then updates ``project-docs/review-matrix.csv`` so every tracked
file has an up-to-date summary:

* Python files receive either ``clean`` when Ruff reports no findings or a
  summary string such as ``3 issues: F401,F841``.
* Non-Python files are marked ``N/A`` because Ruff does not analyse them.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


MATRIX_PATH = Path("project-docs/review-matrix.csv")
LINT_COLUMN = "lint_warnings"


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return Path(result.stdout.strip())


def run_ruff(repo_root: Path) -> List[Dict[str, object]]:
    """Execute ruff via uvx and return JSON diagnostics."""
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", os.path.join(tempfile.gettempdir(), "uv-cache"))
    env.setdefault("UV_TOOL_DIR", os.path.join(tempfile.gettempdir(), "uv-tools"))

    process = subprocess.run(
        ["uvx", "ruff", "check", "--output-format", "json"],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if process.stderr:
        sys.stderr.write(process.stderr)

    try:
        diagnostics = json.loads(process.stdout or "[]")
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise RuntimeError(
            "Failed to parse Ruff JSON output; see stderr for details"
        ) from exc

    return diagnostics


def summarise_diagnostics(
    diagnostics: Iterable[Dict[str, object]], repo_root: Path
) -> Dict[str, str]:
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for entry in diagnostics:
        filename = entry.get("filename")
        if not filename:
            continue
        try:
            rel_path = str(Path(filename).resolve().relative_to(repo_root))
        except ValueError:
            # Skip entries outside the repository.
            continue
        grouped[rel_path].append(entry)

    summaries: Dict[str, str] = {}
    for rel_path, entries in grouped.items():
        codes = sorted({str(entry.get("code")) for entry in entries if entry.get("code")})
        count = len(entries)
        summaries[rel_path] = f"{count} {'issue' if count == 1 else 'issues'}: {','.join(codes)}"
    return summaries


def load_matrix(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Review matrix not found at {path}. Run generate_review_matrix.py first."
        )
    with path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if LINT_COLUMN not in reader.fieldnames:
            raise ValueError(
                f"Matrix at {path} does not contain '{LINT_COLUMN}' column."
            )
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames)
    return rows, fieldnames


def update_matrix(rows: List[Dict[str, str]], summaries: Dict[str, str]) -> None:
    for row in rows:
        rel_path = row.get("path", "")
        if not rel_path:
            continue
        if rel_path.endswith(".py"):
            summary = summaries.get(rel_path)
            row[LINT_COLUMN] = summary or "clean"
        else:
            row[LINT_COLUMN] = "N/A"


def write_matrix(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    repo_root = git_root()
    diagnostics = run_ruff(repo_root)
    summaries = summarise_diagnostics(diagnostics, repo_root)
    rows, fieldnames = load_matrix(MATRIX_PATH)
    update_matrix(rows, summaries)
    write_matrix(MATRIX_PATH, fieldnames, rows)
    print(  # noqa: T201
        f"Updated {MATRIX_PATH} with lint summaries for {len(summaries)} Python files."
    )


if __name__ == "__main__":
    main()
