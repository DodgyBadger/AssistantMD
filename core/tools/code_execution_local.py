"""
Constrained local code execution tool for chat-side cache inspection and small
Python tasks.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.authoring.runtime import (
    AuthoringMontyExecutionError,
    WorkflowAuthoringHost,
    run_authoring_monty,
)
from core.logger import UnifiedLogger

from .base import BaseTool


logger = UnifiedLogger(tag="code-execution-local-tool")


class CodeExecutionLocal(BaseTool):
    """Execute one constrained local Python snippet in the current chat session."""

    allow_routing = False

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the chat-scoped constrained local code execution tool."""

        async def code_execution_local(
            ctx: RunContext,
            *,
            code: str = "",
        ) -> str:
            """Run constrained local Python in the current chat session.

            :param code: Optional constrained-Python snippet to execute
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "code_execution_local"},
                )

                deps = getattr(ctx, "deps", None)
                session_id = str(getattr(deps, "session_id", "") or "").strip()
                vault_name = str(getattr(deps, "vault_name", "") or "").strip()
                reference_date = getattr(deps, "context_manager_now", None) or datetime.today()
                if not session_id or not vault_name:
                    return (
                        "code_execution_local requires chat session context with both "
                        "vault_name and session_id available."
                    )
                if not code.strip():
                    return cls.get_instructions().strip()

                workflow_id = f"{vault_name}/chat/{session_id}"
                host = WorkflowAuthoringHost(
                    workflow_id=workflow_id,
                    vault_path=vault_path,
                    reference_date=reference_date,
                    session_key=session_id,
                    chat_session_id=session_id,
                    message_history=list(getattr(deps, "message_history", []) or []),
                )
                result = await run_authoring_monty(
                    workflow_id=workflow_id,
                    code=code,
                    host=host,
                    script_name="chat_explore.py",
                )
                return cls._format_execution_result(result.value, result.prints)
            except AuthoringMontyExecutionError as exc:
                return cls._format_execution_error(str(exc))
            except Exception as exc:  # noqa: BLE001
                return cls._format_execution_error(str(exc))

        return Tool(
            code_execution_local,
            name="code_execution_local",
            description="Run constrained local Python against the current chat session and current AssistantMD runtime.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for constrained local code execution."""
        return """
Run constrained local Python against the current chat session and current AssistantMD runtime.

Use this for small Python tasks tied to chat history, cached tool artifacts, or vault files.

Full documentation:
- `__virtual_docs__/tools/code_execution_local.md`

Important notes:
- pass code with `code="..."`
- always use named arguments
- use tools such as `file_ops_safe` and `memory_ops` through `call_tool(...)` for access work
- this tool exposes constrained helpers such as `read_cache`, `pending_files`, `generate`, `call_tool`, `assemble_context`, `parse_markdown`, and `finish`
"""

    @staticmethod
    def _format_execution_result(value: Any, prints: tuple[str, ...]) -> str:
        if isinstance(value, str) and value.strip():
            if prints:
                return f"{value}\n\n[prints]\n" + "\n".join(prints)
            return value

        if value is not None:
            try:
                rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            except (TypeError, ValueError):
                rendered = str(value)
            if prints:
                return f"{rendered}\n\n[prints]\n" + "\n".join(prints)
            return rendered

        if prints:
            return "\n".join(prints)

        return "code_execution_local completed with no return value."

    @classmethod
    def _format_execution_error(cls, message: str) -> str:
        hint = cls._hint_for_execution_error(message)
        if hint:
            return f"code_execution_local failed: {message}\n\nHint: {hint}"
        return f"code_execution_local failed: {message}"

    @staticmethod
    def _hint_for_execution_error(message: str) -> str | None:
        lowered = str(message or "").lower()
        if "multi-module import statements" in lowered:
            return (
                "Monty currently expects one import per line. Split grouped imports like "
                "`import re, json` into separate statements."
            )
        if "takes no keyword arguments" in lowered and "re.findall" in lowered:
            return (
                "Prefer positional regex arguments in Monty, for example "
                "`re.findall(pattern, text)` or `re.findall(pattern, text, re.IGNORECASE)`."
            )
        if "name 'json' is not defined" in lowered:
            return (
                "Import stdlib modules explicitly inside the snippet, for example "
                "`import json`, or use simpler string/Python structures when possible."
            )
        if "unable to find 'parse_markdown' in external functions dict" in lowered:
            return (
                "Use the current `code_execution_local` surface and helper docs at "
                "`__virtual_docs__/tools/code_execution_local.md`; this should now be available."
            )
        return None
