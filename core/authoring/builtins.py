"""Built-in capabilities for the experimental Monty-backed authoring runtime."""

from __future__ import annotations

import inspect
from typing import Any

from core.authoring.contracts import (
    BUILTIN_CAPABILITY_NAMES,
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    CapabilityHandlerMissingError,
)
from core.authoring.registry import AuthoringCapabilityRegistry


def create_builtin_registry() -> AuthoringCapabilityRegistry:
    """Build the default built-in capability registry."""
    registry = AuthoringCapabilityRegistry()
    registry.register_many(
        [
            _host_dispatch_capability(
                name="retrieve",
                handler_name="handle_retrieve",
                doc=(
                    "Retrieve scoped external inputs such as files, cache, or recent runs."
                ),
                contract=_retrieve_contract(),
            ),
            _host_dispatch_capability(
                name="output",
                handler_name="handle_output",
                doc="Emit selected results to files or cache sinks.",
                contract=_output_contract(),
            ),
            _host_dispatch_capability(
                name="generate",
                handler_name="handle_generate",
                doc="Run an explicit model generation within frontmatter policy.",
                contract=_generate_contract(),
            ),
            _host_dispatch_capability(
                name="call_tool",
                handler_name="handle_call_tool",
                doc="Call one declared host tool and return its inline result plus metadata.",
                contract=_call_tool_contract(),
            ),
            _host_dispatch_capability(
                name="assemble_context",
                handler_name="handle_assemble_context",
                doc=(
                    "Assemble validated structured chat context from retrieved history, "
                    "instructions, and explicit latest-user input."
                ),
                contract=_assemble_context_contract(),
            ),
            _host_dispatch_capability(
                name="import_content",
                handler_name="handle_import_content",
                doc="Import external content through the host ingestion pipeline.",
                contract=_placeholder_contract(
                    "import_content",
                    "import_content(*, source: str, options: dict | None = None)",
                ),
            ),
            _host_dispatch_capability(
                name="finish",
                handler_name="handle_finish",
                doc="End execution intentionally with a structured terminal status.",
                contract=_finish_contract(),
            ),
        ]
    )
    return registry


def _host_dispatch_capability(
    *,
    name: str,
    handler_name: str,
    doc: str,
    contract: dict[str, Any],
) -> AuthoringCapabilityDefinition:
    if name not in BUILTIN_CAPABILITY_NAMES:
        raise ValueError(f"Unknown built-in capability '{name}'")

    async def _handler(
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any:
        host_handler = getattr(context.host, handler_name, None)
        if host_handler is None:
            raise CapabilityHandlerMissingError(
                f"Host does not implement '{handler_name}' for capability '{name}'"
            )
        result = host_handler(call, context)
        if inspect.isawaitable(result):
            return await result
        return result

    return AuthoringCapabilityDefinition(
        name=name,
        doc=doc,
        handler=_handler,
        contract=contract,
    )


def _placeholder_contract(name: str, signature: str) -> dict[str, Any]:
    return {
        "signature": signature,
        "summary": f"Experimental built-in capability '{name}'.",
        "types": {},
        "return_shape": {},
        "examples": [],
    }


def _retrieve_contract() -> dict[str, Any]:
    return {
        "signature": "retrieve(*, type: str, ref: str, options: dict | None = None)",
        "summary": (
            "Retrieve scoped external inputs. The host interprets ref according to type "
            "and validates options against the published per-type schema."
        ),
        "types": {
            "file": {
                "ref": "Vault-relative file path or selector pattern.",
                "options": {
                    "refs_only": {
                        "type": "bool",
                        "default": False,
                        "description": "Return file references and metadata without loading textual file bodies.",
                    },
                    "pending": {
                        "type": "enum",
                        "values": ["include", "only"],
                        "default": "include",
                        "description": "When set to 'only', resolve only unprocessed files for the pattern.",
                    },
                },
            },
            "cache": {
                "ref": "Logical cache reference scoped by the host execution owner.",
                "options": {},
            },
            "run": {
                "ref": "Currently only 'session' is supported. Retrieves chat history for the active chat session.",
                "options": {
                    "limit": {
                        "type": "int|string",
                        "default": "all",
                        "description": "Number of recent runs to retrieve, or 'all' for the full session history.",
                    },
                },
            },
        },
        "return_shape": {
            "type": "Requested type value.",
            "ref": "Original reference passed by the author.",
            "items": [
                {
                    "ref": "Resolved item reference, usually a vault-relative path without extension normalization surprises.",
                    "content": "Loaded content when available.",
                    "exists": "Whether the referenced item was found.",
                    "metadata": {
                        "filename": "Base filename without extension when available.",
                        "filepath": "Vault-relative path normalized without the implicit .md suffix.",
                        "source_path": "Vault-relative source path including extension when available.",
                        "extension": "Resolved file extension such as .md or .png.",
                        "size_bytes": "Filesystem size for found files.",
                        "char_count": "Exact text character count for textual files.",
                        "token_estimate": "Approximate token count for textual files.",
                        "mtime_epoch": "Modification time as a Unix timestamp.",
                        "ctime_epoch": "Creation/change time as a Unix timestamp.",
                        "mtime": "Modification time as an ISO-8601 UTC string.",
                        "ctime": "Creation/change time as an ISO-8601 UTC string.",
                        "filename_dt": "Parsed filename date as an ISO-8601 UTC string when common patterns are detected.",
                        "error": "Host-provided error string when resolution fails.",
                    },
                }
            ],
        },
        "examples": [
            {
                "code": 'await retrieve(type="file", ref="notes/today.md")',
                "description": "Load one file by vault-relative path.",
            },
            {
                "code": (
                    'notes = await retrieve(type="file", ref="notes/*.md")\n'
                    'latest_three = sorted(\n'
                    '    [item for item in notes.items if item.exists],\n'
                    '    key=lambda item: item.metadata.get("mtime_epoch") or 0,\n'
                    '    reverse=True,\n'
                    ')[:3]'
                ),
                "description": "Retrieve files, then sort and slice explicitly in Python using metadata.",
            },
            {
                "code": 'await retrieve(type="file", ref="notes/*.md", options={"pending": "only", "refs_only": True})',
                "description": "Enumerate pending file refs without loading file bodies into content fields.",
            },
            {
                "code": 'await retrieve(type="cache", ref="research/browser-page")',
                "description": "Load one previously stored cache artifact by logical reference.",
            },
            {
                "code": 'await retrieve(type="run", ref="session", options={"limit": 3})',
                "description": "Load recent chat history for the active session as structured items.",
            },
        ],
    }


def _output_contract() -> dict[str, Any]:
    return {
        "signature": "output(*, type: str, ref: str, data: object, options: dict | None = None)",
        "summary": (
            "Write selected results to a scoped sink. The host interprets ref according "
            "to type and validates options against the published per-type schema."
        ),
        "types": {
            "file": {
                "ref": "Vault-relative output path.",
                "options": {
                    "mode": {
                        "type": "enum",
                        "values": ["append", "replace", "new"],
                        "default": "append",
                        "description": "Write mode forwarded to the shared workflow output runtime.",
                    },
                },
            },
            "cache": {
                "ref": "Logical cache reference scoped by the host execution owner.",
                "options": {
                    "mode": {
                        "type": "enum",
                        "values": ["append", "replace"],
                        "default": "append",
                        "description": "Append to or replace the current cache artifact value.",
                    },
                    "ttl": {
                        "type": "string",
                        "default": "session",
                        "description": "Cache lifetime using the shared cache semantics: session, daily, weekly, or a duration like 30m.",
                    },
                },
            }
        },
        "return_shape": {
            "type": "Requested type value.",
            "ref": "Original reference passed by the author.",
            "status": "High-level write status.",
            "item": {
                "ref": "Requested sink reference.",
                "resolved_ref": "Actual written reference, including numbered paths for mode='new'.",
                "mode": "Resolved write mode.",
            },
        },
        "examples": [
            {
                "code": 'await output(type="file", ref="reports/daily.md", data=summary_text)',
                "description": "Append output to a vault-relative file.",
            },
            {
                "code": (
                    'await output(type="file", ref="reports/daily.md", data=summary_text, '
                    'options={"mode": "replace"})'
                ),
                "description": "Replace an existing file using the shared output runtime.",
            },
            {
                "code": (
                    'await output(type="cache", ref="research/browser-page", data=page_text, '
                    'options={"mode": "replace", "ttl": "24h"})'
                ),
                "description": "Store a temporary cache artifact for later scripted exploration.",
            },
        ],
    }


def _generate_contract() -> dict[str, Any]:
    return {
        "signature": (
            "generate(*, prompt: str, instructions: str | None = None, "
            "model: str | None = None, cache: str | dict | None = None, "
            "options: dict | None = None)"
        ),
        "summary": (
            "Run one explicit model generation using the shared agent runtime. "
            "Instructions are first-class, while generation caching and less common "
            "model controls stay explicit."
        ),
        "arguments": {
            "prompt": {
                "type": "string",
                "required": True,
                "description": "Primary user prompt passed to the shared agent runtime.",
            },
            "instructions": {
                "type": "string",
                "required": False,
                "description": "Additional system-style instructions layered onto the agent.",
            },
            "model": {
                "type": "string",
                "required": False,
                "description": "Optional model alias resolved through the existing model directive.",
            },
            "cache": {
                "type": "string | object",
                "required": False,
                "description": (
                    "Optional host-managed generation cache policy. Use the same TTL "
                    "semantics as cache artifacts: session, daily, weekly, or a "
                    "duration like 10m/24h. Use this for generation memoization. "
                    "Use output(type=\"cache\", ...) when you want a named retrievable "
                    "cache artifact."
                ),
                "schema": {
                    "string_form": "session | daily | weekly | <duration>",
                    "object_form": {
                        "mode": {
                            "type": "string",
                            "description": "Cache mode using the same values as the string form.",
                        }
                    },
                },
            },
            "options": {
                "type": "object",
                "required": False,
                "description": "Less common generation controls.",
                "schema": {
                    "thinking": {
                        "type": "bool",
                        "description": "When model aliases support it, append thinking=true/false to the model directive.",
                    }
                },
            },
        },
        "return_shape": {
            "status": "High-level generation status such as generated or cached.",
            "model": "Resolved model alias or default indicator.",
            "output": "Generated output text.",
        },
        "notes": [
            (
                "generate(..., cache=...) provides host-managed memoization for repeated "
                "generation calls with the same inputs."
            ),
            (
                "Use output(type=\"cache\", ...) when you want a named retrievable "
                "artifact for later scripted access."
            ),
        ],
        "examples": [
            {
                "code": (
                    'await generate(prompt="Summarize this note", '
                    'instructions="Be concise and factual.")'
                ),
                "description": "Use the default model with extra instructions.",
            },
            {
                "code": (
                    'await generate(prompt="Draft a reply", instructions="Warm tone.", '
                    'model="test", options={"thinking": False})'
                ),
                "description": "Use an explicit model alias with a supported generation option.",
            },
            {
                "code": (
                    'await generate(prompt="Summarize these notes", '
                    'instructions="Be concise.", model="test", cache="daily")'
                ),
                "description": "Cache a deterministic generation result using existing cache TTL semantics.",
            },
        ],
    }


def _call_tool_contract() -> dict[str, Any]:
    return {
        "signature": "call_tool(*, name: str, arguments: dict | None = None, options: dict | None = None)",
        "summary": (
            "Call one declared host tool by configured tool name. Arguments are passed "
            "as keyword arguments to the tool. The current MVP returns inline output plus metadata only."
        ),
        "arguments": {
            "name": {
                "type": "string",
                "required": True,
                "description": "Configured tool name from system settings and authoring frontmatter.",
            },
            "arguments": {
                "type": "dict",
                "required": False,
                "description": "Keyword arguments forwarded directly to the resolved tool.",
            },
            "options": {
                "type": "dict",
                "required": False,
                "description": "Reserved for future host-side behavior. The MVP requires this to be empty or omitted.",
            },
        },
        "return_shape": {
            "name": "Configured tool name that was invoked.",
            "status": "High-level result status.",
            "output": "Inline textual tool result.",
            "metadata": "Host-owned metadata for result inspection and future expansion.",
        },
        "examples": [
            {
                "code": (
                    'await call_tool(name="workflow_run", arguments={"operation": "list"})'
                ),
                "description": "List workflows in the current vault using the configured workflow tool.",
            },
            {
                "code": (
                    'await call_tool('
                    'name="internal_api", '
                    'arguments={"endpoint": "authoring_contract"}'
                    ")"
                ),
                "description": "Read structured internal metadata through an allowlisted internal tool.",
            },
        ],
    }


def _assemble_context_contract() -> dict[str, Any]:
    return {
        "signature": (
            "assemble_context(*, history: list | tuple | None = None, "
            "context_messages: list | tuple | None = None, "
            "instructions: list[str] | tuple[str, ...] | None = None, "
            "latest_user_message: object | None = None)"
        ),
        "summary": (
            "Build validated structured downstream chat context from retrieved history "
            "and explicit instruction/context layers."
        ),
        "arguments": {
            "history": {
                "type": "list|tuple",
                "required": False,
                "description": "Structured message-like items to preserve in order.",
            },
            "context_messages": {
                "type": "list|tuple",
                "required": False,
                "description": "Additional system-context messages injected ahead of preserved history.",
            },
            "instructions": {
                "type": "list|tuple",
                "required": False,
                "description": "Extra downstream chat instructions injected as separate system messages.",
            },
            "latest_user_message": {
                "type": "object",
                "required": False,
                "description": "Optional explicit latest user message appended last.",
            },
        },
        "return_shape": {
            "messages": [
                {
                    "role": "Normalized role such as system, user, or assistant.",
                    "content": "Text content for the downstream chat message.",
                    "metadata": "Host-owned metadata retained from normalization.",
                }
            ],
            "instructions": "Normalized downstream instruction strings included in assembly.",
        },
        "examples": [
            {
                "code": (
                    'history = await retrieve(type="run", ref="session", options={"limit": 3})\n'
                    'final = await assemble_context(history=history.items)'
                ),
                "description": "Preserve recent chat history as structured downstream context.",
            },
            {
                "code": (
                    'history = await retrieve(type="run", ref="session", options={"limit": 3})\n'
                    'final = await assemble_context(\n'
                    '    history=history.items,\n'
                    '    instructions=["Prefer exact quoted text when possible."],\n'
                    ')\n'
                ),
                "description": "Add downstream instructions without flattening them into the transcript.",
            },
        ],
    }


def _finish_contract() -> dict[str, Any]:
    return {
        "signature": 'finish(*, status: str = "completed", reason: str | None = None)',
        "summary": (
            "End execution intentionally with a terminal status instead of raising an error."
        ),
        "arguments": {
            "status": {
                "type": "string",
                "required": False,
                "description": "Terminal status. Supported values are completed and skipped.",
            },
            "reason": {
                "type": "string",
                "required": False,
                "description": "Optional human-readable reason recorded in execution logs and results.",
            },
        },
        "return_shape": {
            "status": "Resolved terminal status.",
            "reason": "Structured reason string when provided.",
        },
        "examples": [
            {
                "code": 'await finish(status="skipped", reason="No inputs matched today.")',
                "description": "Exit early without treating the workflow as a failure.",
            },
        ],
    }
