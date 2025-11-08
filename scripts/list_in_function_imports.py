#!/usr/bin/env python3
"""
Report Python imports defined inside functions or methods.

This script walks the repository AST to find any `import` or `from ... import`
statements whose parent is a function (sync or async). These often indicate
hidden dependencies or slow start-up paths and should typically be moved to
module scope unless lazy loading is intentional.
"""
from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class Finding:
    path: Path
    lineno: int
    col_offset: int
    source: str

    def relative_to(self, root: Path) -> "Finding":
        return Finding(
            path=self.path.relative_to(root),
            lineno=self.lineno,
            col_offset=self.col_offset,
            source=self.source,
        )


class ImportVisitor(ast.NodeVisitor):
    """Collect import statements inside function bodies."""

    def __init__(self) -> None:
        self._parents: List[ast.AST] = []
        self.findings: List[Finding] = []

    def visit(self, node: ast.AST) -> None:  # type: ignore[override]
        self._parents.append(node)
        super().visit(node)
        self._parents.pop()

    def _inside_function(self) -> bool:
        return any(isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) for parent in self._parents[:-1])

    def visit_Import(self, node: ast.Import) -> None:
        if self._inside_function():
            source = "import " + ", ".join(alias.name for alias in node.names)
            self.findings.append(
                Finding(
                    path=Path(""),  # filled later
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    source=source,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._inside_function():
            module = node.module or ""
            source = f"from {module} import " + ", ".join(alias.name for alias in node.names)
            self.findings.append(
                Finding(
                    path=Path(""),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    source=source,
                )
            )
        self.generic_visit(node)


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return Path(result.stdout.strip())


def list_tracked_python_files(root: Path) -> List[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [root / line.strip() for line in result.stdout.splitlines() if line.strip()]


def analyze_file(path: Path) -> List[Finding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    visitor = ImportVisitor()
    visitor.visit(tree)

    findings: List[Finding] = []
    for finding in visitor.findings:
        findings.append(
            Finding(
                path=path,
                lineno=finding.lineno,
                col_offset=finding.col_offset,
                source=finding.source,
            )
        )
    return findings


def group_findings(findings: Iterable[Finding]) -> Dict[Path, List[Finding]]:
    grouped: Dict[Path, List[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.path, []).append(finding)
    for items in grouped.values():
        items.sort(key=lambda f: (f.lineno, f.col_offset))
    return grouped


def main() -> None:
    root = git_root()
    files = list_tracked_python_files(root)

    findings: List[Finding] = []
    for path in files:
        findings.extend(analyze_file(path))

    if not findings:
        print("No in-function imports found.")  # noqa: T201
        return

    grouped = group_findings(findings)
    total = 0
    for path in sorted(grouped):
        rel_path = path.relative_to(root)
        print(f"\n{rel_path}")  # noqa: T201
        for finding in grouped[path]:
            total += 1
            print(f"  {finding.lineno}:{finding.col_offset}  {finding.source}")  # noqa: T201

    print(f"\nTotal findings: {total}")  # noqa: T201


if __name__ == "__main__":
    main()
