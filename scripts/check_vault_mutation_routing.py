#!/usr/bin/env python3
"""Check that new vault mutations use the shared mutation API."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


SCAN_ROOTS = (
    Path("core/tools"),
    Path("core/authoring/helpers"),
    Path("core/ingestion"),
    Path("api"),
)

ALLOWED_DIRECT_MUTATION_FILES = {
    Path("core/tools/file_ops_safe.py"),
    Path("core/tools/file_ops_unsafe.py"),
    Path("core/ingestion/storage.py"),
    Path("core/ingestion/service.py"),
    Path("core/tools/workflow_run.py"),
    Path("api/services.py"),
}

MUTATING_METHODS = {
    "write_text",
    "write_bytes",
    "unlink",
    "rename",
    "rmdir",
}

MUTATING_FUNCTIONS = {
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("shutil", "move"),
    ("shutil", "rmtree"),
}


def main() -> int:
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if path in ALLOWED_DIRECT_MUTATION_FILES:
                continue
            offenders.extend(_find_direct_mutations(path))

    if not offenders:
        print("Vault mutation routing check passed.")
        return 0

    print(
        "Vault mutation routing check failed.\n"
        "New vault-mutating code should route through core.vault_state.file_mutations.\n"
        "Direct mutation primitives were found:"
    )
    for offender in offenders:
        print(f"  - {offender}")
    return 1


def _find_direct_mutations(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name == "open" and _open_mode_is_mutating(node):
            offenders.append(f"{path}:{node.lineno}: open mutating mode")
        if name in {f".{method}" for method in MUTATING_METHODS}:
            offenders.append(f"{path}:{node.lineno}: {name}")
        if any(name == f"{module}.{function}" for module, function in MUTATING_FUNCTIONS):
            offenders.append(f"{path}:{node.lineno}: {name}")
    return offenders


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _call_name(node.value)
        if owner and not owner.startswith("."):
            return f"{owner}.{node.attr}"
        return f".{node.attr}"
    return ""


def _open_mode_is_mutating(node: ast.Call) -> bool:
    mode = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    if not isinstance(mode, str):
        return False
    return any(flag in mode for flag in ("w", "a", "x", "+"))


if __name__ == "__main__":
    sys.exit(main())
