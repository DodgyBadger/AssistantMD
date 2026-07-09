"""Deferred inline-review tool for creating vault files."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.vault_state.file_operations import (
    VaultFileOperationRejected,
    prepare_create_file,
    write_prepared_create_file,
)

from .base import BaseTool


logger = UnifiedLogger(tag="review-create-file-tool")


class ReviewCreateFileTool(BaseTool):
    """Create a vault file after inline chat review."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Return the Pydantic AI tool implementation."""

        def review_create_file(*, path: str, content: str) -> ToolReturn:
            """Create a vault file after inline review.

            :param path: Vault-relative file path to create.
            :param content: Full file content to write.
            """
            resolved_vault_path = Path(vault_path or "").resolve()
            try:
                if not vault_path:
                    raise VaultFileOperationRejected(
                        "vault_path_required",
                        "vault_path is required for reviewed file creation.",
                    )
                prepared = prepare_create_file(
                    vault_path=resolved_vault_path,
                    path=path,
                    content=content,
                )
                result = write_prepared_create_file(
                    vault_path=resolved_vault_path,
                    prepared=prepared,
                )
            except VaultFileOperationRejected as exc:
                return _result(
                    status="error",
                    message=str(exc),
                    path=path,
                    error_type=exc.code,
                    metadata=exc.details,
                )

            logger.add_sink("validation").info(
                "tool_invoked",
                data={
                    "tool": "review_create_file",
                    "vault": resolved_vault_path.name,
                    "path": result.path,
                },
            )
            return _result(
                status="completed",
                message=f"Created @{result.path}.",
                path=result.path,
                metadata={
                    "operation": "create_file",
                    "before_exists": result.before_exists,
                    "after_exists": result.after_exists,
                    "before_hash": result.before_hash,
                    "after_hash": result.after_hash,
                },
            )

        return Tool(
            review_create_file,
            name="review_create_file",
            description=(
                "Create one vault file after inline user review. The call pauses "
                "for review before writing, then resumes the chat run after the "
                "user approves or denies it."
            ),
            requires_approval=True,
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Return usage instructions for this tool."""
        return """
Use `review_create_file` when you want to create one vault file through the
inline review card workflow.

Pass:
- `path`: vault-relative destination path.
- `content`: the complete file content.

The tool pauses before writing. After the user approves, the file is created
through the normal vault mutation path. Parent directories are created as
needed.
"""


def _result(
    *,
    status: str,
    message: str,
    path: str,
    error_type: str | None = None,
    metadata: dict | None = None,
) -> ToolReturn:
    payload = {
        "status": status,
        "tool_name": "review_create_file",
        "operation": "create_file",
        "path": path,
    }
    if error_type:
        payload["error_type"] = error_type
    if metadata:
        payload.update(metadata)
    return ToolReturn(
        return_value=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        metadata=payload,
    )
