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
            code: str,
            readable_cache_refs: list[str] | None = None,
            writable_cache_refs: list[str] | None = None,
        ) -> str:
            """Run constrained local Python in the current chat session.

            :param code: Constrained-Python snippet to execute
            :param readable_cache_refs: Cache refs or glob patterns the snippet may retrieve
            :param writable_cache_refs: Cache refs or glob patterns the snippet may write
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
                    return "code_execution_local requires a non-empty code snippet."

                workflow_id = f"{vault_name}/chat/{session_id}"
                frontmatter = {
                    "authoring.capabilities": ["retrieve", "output", "generate"],
                    "authoring.retrieve.cache": list(readable_cache_refs or []),
                    "authoring.output.cache": list(writable_cache_refs or []),
                }
                host = WorkflowAuthoringHost(
                    workflow_id=workflow_id,
                    vault_path=vault_path,
                    reference_date=reference_date,
                    session_key=session_id,
                )
                result = await run_authoring_monty(
                    workflow_id=workflow_id,
                    code=code,
                    host=host,
                    frontmatter=frontmatter,
                    script_name="chat_explore.py",
                )
                return cls._format_execution_result(result.value, result.prints)
            except AuthoringMontyExecutionError as exc:
                return f"code_execution_local failed: {exc}"
            except Exception as exc:  # noqa: BLE001
                return f"code_execution_local failed: {exc}"

        return Tool(code_execution_local, name="code_execution_local")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for constrained local code execution."""
        return """
## code_execution_local usage instructions

Use this for:
- small calculations and transformations
- iterative inspection of cached artifacts by ref
- tightly scoped local summarization or extraction loops

This is NOT generic local Python. It runs in a constrained sandbox with a small
host API and current chat-session cache access only.

What it supports well right now:
- `retrieve(type="cache", ref=...)`
- `output(type="cache", ref=..., data=...)`
- `generate(...)`
- ordinary Python logic around those calls

What it does NOT currently provide by default:
- arbitrary file access
- arbitrary tool access
- unrestricted stdlib / OS access
- multi-language execution

If you need broader language support or a more general remote sandbox, use the
Piston-backed `code_execution` tool instead.

Required arguments:
- code_execution_local(code="...", readable_cache_refs=["tool/..."])

Optional arguments:
- writable_cache_refs=["scratch/*"] to persist derived cache artifacts

Patterns:
- Simple calculation:
  code_execution_local(
    code=\"\"\"
total = sum([17, 23, 41])
str(total)
\"\"\",
  )

- Retrieve and inspect a cached artifact:
  code_execution_local(
    code=\"\"\"
artifact = await retrieve(type="cache", ref="tool/example/ref")
artifact.items[0].content[:2000]
\"\"\",
    readable_cache_refs=["tool/example/ref"],
  )

- Summarize a cached artifact:
  code_execution_local(
    code=\"\"\"
artifact = await retrieve(type="cache", ref="tool/example/ref")
summary = await generate(
    prompt=artifact.items[0].content[:4000],
    instructions="Summarize the main points briefly.",
)
summary.output
\"\"\",
    readable_cache_refs=["tool/example/ref"],
  )

Notes:
- This tool runs in the current chat session cache namespace only.
- Grant the narrowest `readable_cache_refs` patterns that fit the task.
- Prefer returning a compact final value rather than printing large text.
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
