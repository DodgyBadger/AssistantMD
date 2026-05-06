"""Diff a vault file against its latest retained previous snapshot."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.vault_state.diff import diff_file_against_previous

from .base import BaseTool


logger = UnifiedLogger(tag="diff-file-tool")


class DiffFile(BaseTool):
    """Vault diff tool backed by task mutation snapshots."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Get the Pydantic AI tool for vault file diffs."""

        def diff_file(
            *,
            path: str = "",
        ) -> ToolReturn:
            """Compare a vault file's current content to its latest retained previous snapshot.

            :param path: Vault-relative file path to diff
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "diff_file"},
                )
                if not vault_path:
                    raise ValueError("vault_path is required for diff_file")
                normalized_path = str(path or "").strip()
                if not normalized_path:
                    return cls._result(
                        message="diff_file requires a non-empty path.",
                        status="error",
                        path="",
                        reason="missing_path",
                        error_type="invalid_parameters",
                    )

                result = diff_file_against_previous(
                    vault_path=vault_path,
                    path=normalized_path,
                )
                logger.add_sink("validation").info(
                    "diff_file_completed",
                    data={
                        "path": result.path,
                        "available": result.available,
                        "status": result.status,
                        "reason": result.reason,
                        "has_changes": result.has_changes,
                    },
                )
                return cls._result_from_diff(result)
            except Exception as exc:  # noqa: BLE001
                return cls._result(
                    message=f"Error diffing file: {exc}",
                    status="error",
                    path=str(path or "").strip(),
                    reason=type(exc).__name__,
                    error_type=type(exc).__name__,
                )

        return Tool(
            diff_file,
            name="diff_file",
            description=(
                "Compare a vault file's current content against its latest retained "
                "previous snapshot and return a unified diff."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for vault file diffs."""
        return """
Full documentation:
- `__virtual_docs__/tools/diff_file.md`
"""

    @classmethod
    def _result_from_diff(cls, result: Any) -> ToolReturn:
        if not result.available:
            return cls._result(
                message=result.message,
                status=result.status,
                path=result.path,
                reason=result.reason,
                available=False,
                has_changes=False,
                payload=cls._metadata_payload(result),
            )
        if not result.has_changes:
            message = f"No changes found for {result.path}."
        else:
            message = result.text
        return cls._result(
            message=message,
            status=result.status,
            path=result.path,
            available=True,
            has_changes=result.has_changes,
            payload=cls._metadata_payload(result),
        )

    @staticmethod
    def _metadata_payload(result: Any) -> dict[str, Any]:
        return {
            "available": result.available,
            "status": result.status,
            "path": result.path,
            "reason": result.reason,
            "message": result.message,
            "has_changes": result.has_changes,
            "format": result.format,
            "baseline": result.baseline,
            "current": result.current,
        }

    @staticmethod
    def _result(
        *,
        message: str,
        status: str,
        path: str,
        reason: str = "",
        available: bool = False,
        has_changes: bool = False,
        error_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ToolReturn:
        metadata: dict[str, Any] = {
            "status": status,
            "path": path,
            "available": available,
            "has_changes": has_changes,
            "format": "unified",
        }
        if reason:
            metadata["reason"] = reason
        if error_type:
            metadata["error_type"] = error_type
        if payload:
            metadata["diff"] = payload
        return ToolReturn(return_value=message, content=None, metadata=metadata)
