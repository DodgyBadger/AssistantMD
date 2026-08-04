#!/usr/bin/env python3
"""Check that API resource access uses authority-mediated runtime services."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SCAN_ROOT = Path("api")

RAW_CHAT_IMPORT_ALLOWLIST = {
    Path("api/services/chat_sessions.py"),
    Path("api/services/shared.py"),
}

RAW_CHAT_ACCESS_ALLOWLIST = {
    Path("api/services/chat_sessions.py"),
}

RAW_TASK_ACCESS_METHODS = {
    "get_task",
    "list_tasks",
    "cancel_task",
    "cancel_scope",
}

RAW_CHAT_ACCESS_METHODS = {
    "get_session",
    "get_session_by_id",
    "list_sessions",
    "ensure_session",
    "delete_sessions",
}


def main() -> int:
    _assert_guard_contract()
    offenders: list[str] = []
    for path in sorted(SCAN_ROOT.rglob("*.py")):
        offenders.extend(_find_raw_resource_access(path))

    if not offenders:
        print("Principal resource routing check passed.")
        return 0

    print(
        "Principal resource routing check failed.\n"
        "API code must use RuntimeContext.chat_session_access or "
        "RuntimeContext.execution_task_access for principal-owned resource "
        "access.\nRaw access was found:"
    )
    for offender in offenders:
        print(f"  - {offender}")
    return 1


def _find_raw_resource_access(
    path: Path,
    *,
    source: str | None = None,
) -> list[str]:
    if source is None:
        source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            offenders.extend(_check_import_from(path, node))
            continue
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        method_name = call_name.rsplit(".", 1)[-1]
        if ".task_coordinator." in call_name and method_name in RAW_TASK_ACCESS_METHODS:
            offenders.append(f"{path}:{node.lineno}: {call_name}")
        if (
            path not in RAW_CHAT_ACCESS_ALLOWLIST
            and method_name in RAW_CHAT_ACCESS_METHODS
            and _looks_like_raw_chat_store_call(call_name)
        ):
            offenders.append(f"{path}:{node.lineno}: {call_name}")

    return offenders


def _assert_guard_contract() -> None:
    """Fail if representative raw access no longer triggers the guard."""
    source = """
from core.chat.chat_store import ChatStore

async def bypass(runtime):
    await runtime.task_coordinator.get_task("task-id")
"""
    offenders = _find_raw_resource_access(
        Path("api/services/guard_self_check.py"),
        source=source,
    )
    if len(offenders) != 2:
        raise RuntimeError(
            "Principal resource routing guard self-check failed: "
            f"expected 2 findings, got {len(offenders)}."
        )


def _check_import_from(path: Path, node: ast.ImportFrom) -> list[str]:
    if path in RAW_CHAT_IMPORT_ALLOWLIST:
        return []
    module_name = node.module or ""
    offenders: list[str] = []
    for alias in node.names:
        if module_name == "core.chat.chat_store" and alias.name == "ChatStore":
            offenders.append(
                f"{path}:{node.lineno}: from {module_name} import {alias.name}"
            )
        if module_name == "shared" and alias.name == "chat_store" and node.level:
            offenders.append(f"{path}:{node.lineno}: raw shared chat_store import")
    return offenders


def _looks_like_raw_chat_store_call(call_name: str) -> bool:
    return any(
        marker in call_name
        for marker in (
            "chat_store.",
            "_chat_store.",
            ".chat_store.",
        )
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _call_name(node.value)
        if owner and not owner.startswith("."):
            return f"{owner}.{node.attr}"
        return f".{node.attr}"
    return ""


if __name__ == "__main__":
    sys.exit(main())
