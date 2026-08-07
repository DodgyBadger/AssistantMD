"""Durable import-to-markdown tool for URLs and vault files."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.ingestion.import_service import ContentImportResult, ContentImportService
from core.logger import UnifiedLogger
from core.tools.base import BaseTool
from core.tools.failures import FailureClassification, tool_failure_return

logger = UnifiedLogger(tag="content-import-tool")


class ContentImport(BaseTool):
    """Submit and inspect durable ingestion jobs in the current vault."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        async def content_import(
            *,
            operation: str,
            sources: str | list[str] | None = None,
            job_ids: int | list[int] | None = None,
            options: dict[str, Any] | None = None,
        ) -> ToolReturn:
            """Import URLs or vault files to Markdown, or inspect import jobs.

            :param operation: One of submit or status.
            :param sources: One source or a list of sources for submit.
            :param job_ids: One job id or a list of job ids for status.
            :param options: Optional destination and validated extraction options for submit.
            """
            op = (operation or "").strip().lower()
            try:
                if not vault_path:
                    raise ValueError("vault_path is required for content_import")
                service = ContentImportService(vault_path)
                if op == "submit":
                    if sources is None or job_ids is not None:
                        raise ValueError(
                            "submit requires sources and does not accept job_ids"
                        )
                    results = service.submit(sources=sources, options=options)
                    logger.set_sinks(["validation"]).info(
                        "content_import_submitted",
                        data={
                            "event": "content_import_submitted",
                            "vault_name": service.vault_name,
                            "accepted_count": len(results),
                            "url_count": sum(
                                item.source_kind == "url" for item in results
                            ),
                            "vault_file_count": sum(
                                item.source_kind == "vault_file" for item in results
                            ),
                            "job_ids": [item.job_id for item in results],
                        },
                    )
                    return _success_result(op, results)
                if op == "status":
                    if job_ids is None or sources is not None or options is not None:
                        raise ValueError(
                            "status requires job_ids and does not accept sources or options"
                        )
                    results = service.status(job_ids=job_ids)
                    logger.set_sinks(["validation"]).info(
                        "content_import_status_read",
                        data={
                            "event": "content_import_status_read",
                            "vault_name": service.vault_name,
                            "requested_count": len(results),
                            "returned_count": len(results),
                        },
                    )
                    return _success_result(op, results)
                raise ValueError("operation must be submit or status")
            except Exception as exc:  # noqa: BLE001 - tool boundary
                return tool_failure_return(
                    tool_name="content_import",
                    message="Content import request failed",
                    classification=FailureClassification(
                        error_type=type(exc).__name__,
                        failure_kind="bad_request",
                        retryable=False,
                        phase="content_import",
                        message=str(exc),
                        suggested_action="Correct the import request before retrying.",
                    ),
                    metadata={"operation": op},
                )

        return Tool(
            content_import,
            name="content_import",
            description=(
                "Submit one or more URLs or vault files for durable import to Markdown, "
                "and inspect the resulting ingestion jobs."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        return """
Full documentation:
- `__virtual_docs__/tools/content_import.md`
"""


def _success_result(
    operation: str,
    results: list[ContentImportResult],
) -> ToolReturn:
    items = [item.to_dict() for item in results]
    if operation == "submit":
        summary = f"Queued {len(items)} content import job(s)."
    else:
        summary = f"Returned {len(items)} content import job status result(s)."
    return ToolReturn(
        return_value=summary,
        metadata={
            "tool_name": "content_import",
            "status": "success",
            "operation": operation,
            "items": items,
        },
    )
