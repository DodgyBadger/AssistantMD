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
                    "Retrieve scoped external inputs such as files, state, or recent runs."
                ),
                contract=_retrieve_contract(),
            ),
            _host_dispatch_capability(
                name="output",
                handler_name="handle_output",
                doc="Emit selected results to files, state, or context sinks.",
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
                doc="Call one declared host tool and return its result or reference.",
                contract=_placeholder_contract(
                    "call_tool",
                    "call_tool(*, name: str, arguments: dict | None = None, options: dict | None = None)",
                ),
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
                    "required": {
                        "type": "bool",
                        "default": False,
                        "description": "Skip/fail semantics for missing file inputs.",
                    },
                    "refs_only": {
                        "type": "bool",
                        "default": False,
                        "description": "Return file references without loading content into prompt-oriented fields.",
                    },
                    "pending": {
                        "type": "enum",
                        "values": ["include", "only"],
                        "default": "include",
                        "description": "When set to 'only', resolve only unprocessed files for the pattern.",
                    },
                    "latest": {
                        "type": "bool",
                        "default": False,
                        "description": "Resolve only the latest matching files using shared selector semantics.",
                    },
                    "limit": {
                        "type": "int",
                        "minimum": 1,
                        "description": "Maximum number of items returned after selector resolution.",
                    },
                    "order": {
                        "type": "enum",
                        "values": ["mtime", "ctime", "alphanum", "filename_dt"],
                        "default": "alphanum",
                        "description": "Ordering strategy forwarded to the shared workflow selector runtime.",
                    },
                    "dir": {
                        "type": "enum",
                        "values": ["asc", "desc"],
                        "default": "asc",
                        "description": "Ordering direction forwarded to the shared workflow selector runtime.",
                    },
                    "dt_pattern": {
                        "type": "string",
                        "description": "Required with order='filename_dt' to parse dates from filenames.",
                    },
                    "dt_format": {
                        "type": "string",
                        "description": "Required with order='filename_dt' to parse dates from filenames.",
                    },
                },
            }
        },
        "return_shape": {
            "type": "Requested type value.",
            "ref": "Original reference passed by the author.",
            "items": [
                {
                    "ref": "Resolved item reference, usually a vault-relative path without extension normalization surprises.",
                    "content": "Loaded content when available.",
                    "exists": "Whether the referenced item was found.",
                    "metadata": "Host-owned metadata for deterministic exploration.",
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
                    'await retrieve(type="file", ref="notes/*.md", '
                    'options={"pending": "only", "order": "ctime", "limit": 5})'
                ),
                "description": "Resolve pending files using the shared workflow selector semantics.",
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
                    "header": {
                        "type": "string",
                        "description": "Optional header text resolved through the shared header formatter.",
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
        ],
    }


def _generate_contract() -> dict[str, Any]:
    return {
        "signature": (
            "generate(*, prompt: str, instructions: str | None = None, "
            "model: str | None = None, options: dict | None = None)"
        ),
        "summary": (
            "Run one explicit model generation using the shared agent runtime. "
            "Instructions are first-class, while less common model controls live in options."
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
            "status": "High-level generation status.",
            "model": "Resolved model alias or default indicator.",
            "output": "Generated output text.",
        },
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
        ],
    }
