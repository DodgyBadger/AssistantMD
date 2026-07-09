"""Tool for creating chat-native collaborative file edit proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.chat.edit_proposals import EditProposalError, create_edit_proposal
from core.logger import UnifiedLogger

from .base import BaseTool


logger = UnifiedLogger(tag="propose-file-edits-tool")


class ProposeFileEditsTool(BaseTool):
    """Create interactive edit proposal artifacts for chat review."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Return the Pydantic AI tool implementation."""

        async def propose_file_edits(
            ctx: RunContext,
            *,
            edits: list[dict[str, Any]],
            title: str = "",
            summary: str = "",
        ) -> ToolReturn:
            """Create an interactive file edit proposal artifact.

            :param edits: Proposed edits. Each item has an operation and
                operation-specific fields, with optional edit_id and rationale.
            :param title: Short title for the proposal card.
            :param summary: Optional summary of the proposed changes.
            """
            deps = getattr(ctx, "deps", None)
            session_id = str(getattr(deps, "session_id", "") or "")
            vault_name = str(getattr(deps, "vault_name", "") or "")
            resolved_vault_path = Path(vault_path or "").resolve()
            if not vault_name and resolved_vault_path.name:
                vault_name = resolved_vault_path.name
            try:
                proposal = create_edit_proposal(
                    vault_name=vault_name,
                    vault_path=resolved_vault_path,
                    session_id=session_id,
                    edits=edits,
                    title=title,
                    summary=summary,
                )
            except EditProposalError as exc:
                return ToolReturn(
                    return_value=json.dumps(
                        {
                            "status": "error",
                            "error_type": exc.code,
                            "message": str(exc),
                            "details": exc.details,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    metadata={
                        "status": "error",
                        "tool_name": "propose_file_edits",
                        "error_type": exc.code,
                    },
                )

            logger.add_sink("validation").info(
                "tool_invoked",
                data={
                    "tool": "propose_file_edits",
                    "vault": vault_name,
                    "session_id": session_id,
                    "artifact_ref": proposal["artifact_ref"],
                    "edit_count": len(proposal.get("edits") or []),
                },
            )
            return ToolReturn(
                return_value=json.dumps(
                    {
                        "status": "ok",
                        "artifact_ref": proposal["artifact_ref"],
                        "artifact_kind": proposal["artifact_kind"],
                        "edit_count": len(proposal.get("edits") or []),
                        "title": proposal["title"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                metadata={
                    "status": "ok",
                    "tool_name": "propose_file_edits",
                    "artifact_ref": proposal["artifact_ref"],
                    "artifact_kind": proposal["artifact_kind"],
                    "edit_count": len(proposal.get("edits") or []),
                },
            )

        return Tool(
            propose_file_edits,
            name="propose_file_edits",
            description=(
                "Create an interactive chat artifact that lets the user review, "
                "edit, select, and apply proposed vault file replacements, "
                "creations, deletions, and moves."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Return usage instructions for the proposal tool."""
        return """
Use `propose_file_edits` when you want the user to approve file changes before
they are written.

Each edit item supports:
- `operation`: `replace_text`, `create_file`, `delete_file`, or `move_file`.
  Omit it for `replace_text`.
- `path`: vault-relative file path.
- `rationale`: optional short reason shown in the proposal card.

For `replace_text`, include `original_text` and the proposed replacement as
`replacement_text` or `content`. The original text must match exactly once.

For `create_file`, include `replacement_text`, `content`, or `initial_content`
with the proposed full file content. The path must not already exist.

For `delete_file`, include the existing `path`.

For `move_file`, include the existing source `path` and a `destination` path
that does not already exist.

Read existing files first with `file_ops_safe` when you are not certain of the
current text or target paths.
"""
