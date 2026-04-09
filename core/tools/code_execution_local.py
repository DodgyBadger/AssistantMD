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

from core.authoring import describe_authoring_contract
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
            readable_cache_refs: list[str] | None = None,
            writable_cache_refs: list[str] | None = None,
            readable_file_paths: list[str] | None = None,
            writable_file_paths: list[str] | None = None,
        ) -> str:
            """Run constrained local Python in the current chat session.

            :param code: Optional constrained-Python snippet to execute
            :param readable_cache_refs: Cache refs or glob patterns the snippet may retrieve
            :param writable_cache_refs: Cache refs or glob patterns the snippet may write
            :param readable_file_paths: Optional explicit file read scope when file_ops_safe is enabled
            :param writable_file_paths: Optional explicit file write scope when file_ops_safe is enabled
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "code_execution_local"},
                )

                deps = getattr(ctx, "deps", None)
                session_id = str(getattr(deps, "session_id", "") or "").strip()
                vault_name = str(getattr(deps, "vault_name", "") or "").strip()
                enabled_tools = {
                    str(name).strip()
                    for name in (getattr(deps, "tools", []) or [])
                    if str(name).strip()
                }
                reference_date = getattr(deps, "context_manager_now", None) or datetime.today()
                if not session_id or not vault_name:
                    return (
                        "code_execution_local requires chat session context with both "
                        "vault_name and session_id available."
                    )
                if not code.strip():
                    return json.dumps(
                        {
                            "usage": cls.get_instructions().strip(),
                            "authoring_contract": describe_authoring_contract(),
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )

                workflow_id = f"{vault_name}/chat/{session_id}"
                allow_file_scope = "file_ops_safe" in enabled_tools
                readable_file_scope = (
                    list(readable_file_paths or ["*"]) if allow_file_scope else []
                )
                writable_file_scope = (
                    list(writable_file_paths or ["*"]) if allow_file_scope else []
                )
                frontmatter = {
                    "authoring.capabilities": ["retrieve", "output", "generate", "assemble_context"],
                    "authoring.retrieve.cache": list(readable_cache_refs or []),
                    "authoring.output.cache": list(writable_cache_refs or []),
                    "authoring.retrieve.file": readable_file_scope,
                    "authoring.output.file": writable_file_scope,
                }
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
                    frontmatter=frontmatter,
                    script_name="chat_explore.py",
                )
                return cls._format_execution_result(result.value, result.prints)
            except AuthoringMontyExecutionError as exc:
                return f"code_execution_local failed: {exc}"
            except Exception as exc:  # noqa: BLE001
                return f"code_execution_local failed: {exc}"

        return Tool(
            code_execution_local,
            name="code_execution_local",
            description="Run constrained local Python against the current chat session, cache scope, and optional vault file scope.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for constrained local code execution."""
        return """
Run constrained local Python against the current chat session, cache scope, and optional vault file scope.

Use this for:
- small calculations and transformations
- iterative inspection of cached artifacts by ref
- direct vault file exploration when chat also has `file_ops_safe`
- tightly scoped local summarization or extraction loops

This tool runs constrained local Python with a small host API and narrow
current-chat execution context.

If you call `code_execution_local()` with no arguments, it returns these usage
instructions plus the current structured authoring contract metadata.

What it supports well right now:
- `retrieve(type="cache", ref=...)`
- `retrieve(type="file", ref=...)` when `file_ops_safe` is enabled for the chat run
- `retrieve(type="run", ref="session", options=...)`
- `output(type="cache", ref=..., data=...)`
- `output(type="file", ref=..., data=...)` when `file_ops_safe` is enabled for the chat run
- `generate(...)`
- `assemble_context(...)`
- ordinary Python logic around those calls

For broader language support or a remote sandbox, use the Piston-backed
`code_execution` tool.

Discovery:
- `code_execution_local()`

Execution:
- `code_execution_local(code="...")`

Optional arguments:
- writable_cache_refs=["scratch/*"] to persist derived cache artifacts
- readable_file_paths=[...] or writable_file_paths=[...] to narrow file scope explicitly

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
    cache="daily",
)
summary.output
\"\"\",
    readable_cache_refs=["tool/example/ref"],
  )

- Retrieve recent chat history and assemble a validated downstream context:
  code_execution_local(
    code=\"\"\"
history = await retrieve(type="run", ref="session", options={"limit": 3})
assembled = await assemble_context(
    history=history.items,
    instructions=["Keep the response concise."],
)
[(message.role, message.content) for message in assembled.messages]
\"\"\",
  )

- Explore a vault file directly when `file_ops_safe` is enabled:
  code_execution_local(
    code=\"\"\"
doc = await retrieve(type="file", ref="notes/project.md")
doc.items[0].content[:2000]
\"\"\",
  )

Notes:
- This tool can always read the current chat session history.
- It can read/write explicitly granted cache refs.
- If chat has `file_ops_safe`, this tool also gets vault file read/write access by default. Use `readable_file_paths` or `writable_file_paths` to narrow that scope when helpful.
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
