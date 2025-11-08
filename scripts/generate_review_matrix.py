#!/usr/bin/env python3
"""
Generate or refresh the review coverage matrix for the repository.

The script walks all tracked files (via `git ls-files`) and writes a CSV with
one row per path plus placeholders for review checkpoints. Existing entries are
preserved so reviewers can keep their notes while ensuring newly added files are
captured automatically.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


DEFAULT_COLUMNS: Sequence[str] = (
    "path",
    "exists",
    "status",
    "owner",
    "lint_warnings",
    "personal_identifiers",
    "logger_usage",
    "code_duplication",
    "docstrings",
    "in_function_imports",
    "leading_underscore_functions",
    "security",
    "defensive_error_handling",
    "refactor_opportunities",
    "last_reviewed",
    "issues",
    "notes",
)
DEFAULT_STATUS = "pending"
REMOVED_STATUS = "removed"


@dataclass(frozen=True)
class ReviewRow:
    """Represents a row in the review matrix."""

    path: str
    data: Dict[str, str]

    def with_defaults(self, columns: Sequence[str], *, exists: bool) -> Dict[str, str]:
        row: Dict[str, str] = {column: "" for column in columns}
        row.update(self.data)
        for key in list(row):
            if key not in columns:
                del row[key]
        row["path"] = self.path
        row["exists"] = "yes" if exists else "no"
        if not row.get("status"):
            row["status"] = DEFAULT_STATUS if exists else REMOVED_STATUS
        if not exists:
            row["status"] = row.get("status", REMOVED_STATUS) or REMOVED_STATUS
        return row


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return Path(result.stdout.strip())


def list_tracked_files(repo_root: Path) -> List[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_existing_matrix(path: Path) -> Dict[str, ReviewRow]:
    if not path.exists():
        return {}
    rows: Dict[str, ReviewRow] = {}
    with path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for raw_row in reader:
            file_path = raw_row.get("path", "").strip()
            if not file_path:
                continue
            rows[file_path] = ReviewRow(path=file_path, data=raw_row)
    return rows


def write_matrix(
    rows: Iterable[Dict[str, str]],
    path: Path,
    columns: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_rows(
    tracked_files: Sequence[str],
    existing_rows: Dict[str, ReviewRow],
    columns: Sequence[str],
) -> List[Dict[str, str]]:
    output_rows: List[Dict[str, str]] = []
    for file_path in tracked_files:
        current = existing_rows.get(file_path)
        if current:
            output_rows.append(current.with_defaults(columns, exists=True))
        else:
            output_rows.append(
                ReviewRow(path=file_path, data={}).with_defaults(columns, exists=True)
            )
    known_paths = set(tracked_files)
    for file_path, review_row in existing_rows.items():
        if file_path in known_paths:
            continue
        output_rows.append(review_row.with_defaults(columns, exists=False))
    output_rows.sort(key=lambda item: item["path"])
    return output_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or refresh the review coverage matrix CSV."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("project-docs/review-matrix.csv"),
        help="Output CSV path (default: project-docs/review-matrix.csv)",
    )
    parser.add_argument(
        "--columns",
        nargs="+",
        help="Override default column order.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    columns: Sequence[str] = tuple(args.columns) if args.columns else DEFAULT_COLUMNS

    repo_root = git_root()
    tracked_files = list_tracked_files(repo_root)
    existing = load_existing_matrix(args.output)
    rows = build_rows(tracked_files, existing, columns)
    write_matrix(rows, args.output, columns)

    print(f"Wrote {len(rows)} rows to {args.output}")  # noqa: T201


if __name__ == "__main__":
    main()
