"""Workstream memory operations tool."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.memory import MemoryContext
from core.memory.workstreams import (
    WorkstreamArtifact,
    WorkstreamStore,
)
from core.vector import VectorService

from .base import BaseTool


logger = UnifiedLogger(tag="memory-ops-tool")


class MemoryOps(BaseTool):
    """Manage workstream memory."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the memory operations tool."""

        async def memory_ops(
            ctx: RunContext,
            *,
            operation: str,
            session_id: str = "",
            vault_name: str = "",
            limit: int | str = "all",
            workstream_id: str = "",
            title: str | None = None,
            status: str | None = None,
            type: str | None = None,
            topic: str | None = None,
            entities: str | None = None,
            project: str | None = None,
            objective: str | None = None,
            strategy: str | None = None,
            field_type: str = "",
            value: str = "",
            artifacts: list[dict[str, Any]] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> str:
            """Manage workstream memory.

            :param operation: Operation name.
            :param session_id: Optional explicit session id. Defaults to the active session when available.
            :param vault_name: Optional explicit vault name. Defaults to active vault when available.
            :param limit: Positive integer or "all"
            :param workstream_id: Workstream id for workstream operations.
            :param title: Workstream title for create/update operations.
            :param status: Workstream status for create/update operations.
            :param type: Workstream type text.
            :param topic: Workstream topic/theme text.
            :param entities: People, organizations, and named entities text.
            :param project: Project/program text.
            :param objective: Objective text.
            :param strategy: Strategy or reusable approach text.
            :param field_type: Field type for search operations.
            :param value: Field value for search operations.
            :param artifacts: Optional list of artifact objects.
            :param metadata: Optional object metadata for create operations.
            """
            try:
                deps = getattr(ctx, "deps", None)
                requested_session_id = str(session_id or "").strip() or None
                requested_vault_name = str(vault_name or "").strip() or None
                op = (operation or "").strip().lower()
                memory_context = MemoryContext.from_deps(deps)
                active_session_id = requested_session_id or memory_context.session_id
                active_vault_name = requested_vault_name or memory_context.vault_name
                store = WorkstreamStore()

                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "memory_ops",
                        "operation": op,
                    },
                )

                resolved_limit = cls._parse_limit(limit)
                if op == "create_workstream":
                    _require(active_vault_name, "vault_name is required")
                    workstream = store.create_workstream(
                        vault_name=active_vault_name,
                        title=title,
                        workstream_id=workstream_id or None,
                        status=status or "active",
                        type=type,
                        topic=topic,
                        entities=entities,
                        project=project,
                        objective=objective,
                        strategy=strategy,
                        metadata=metadata or {},
                    )
                    _maybe_add_artifacts(store, workstream.workstream_id, active_vault_name, artifacts)
                    indexed_fields = await _maybe_index_workstream_fields(
                        store,
                        workstream.workstream_id,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "indexed_fields": indexed_fields,
                        "workstream": store.get_workstream(workstream.workstream_id).to_dict(),
                    }
                elif op == "get_workstream":
                    if workstream_id:
                        workstream = store.get_workstream(workstream_id)
                        status_value = "found" if workstream else "not_found"
                    else:
                        _require(active_vault_name, "vault_name is required")
                        _require(active_session_id, "session_id is required")
                        workstream = store.get_current_workstream(
                            vault_name=active_vault_name,
                            session_id=active_session_id,
                        )
                        status_value = "linked" if workstream else "unlinked"
                    result = {
                        "status": status_value,
                        "operation": op,
                        "vault_name": active_vault_name,
                        "session_id": active_session_id,
                        "workstream": workstream.to_dict() if workstream else None,
                    }
                elif op == "search_workstreams":
                    _require(active_vault_name, "vault_name is required")
                    resolved_search_limit = resolved_limit if isinstance(resolved_limit, int) else 20
                    if field_type and value:
                        matches = await store.search_workstreams_by_field(
                            vault_name=active_vault_name,
                            field_type=field_type,
                            value=value,
                            vector_service=VectorService(),
                            limit=resolved_search_limit,
                        )
                        result = {
                            "status": "ok",
                            "operation": op,
                            "query": {
                                "field_type": field_type,
                                "value": value,
                            },
                            "matches": [match.to_dict() for match in matches],
                            "workstreams": [
                                match.workstream.to_dict() for match in matches
                            ],
                        }
                    else:
                        workstreams = store.search_workstreams(
                            vault_name=active_vault_name,
                            limit=resolved_search_limit,
                        )
                        result = {
                            "status": "ok",
                            "operation": op,
                            "workstreams": [workstream.to_dict() for workstream in workstreams],
                        }
                elif op == "link_session":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    _require(workstream_id, "workstream_id is required")
                    workstream = store.link_session_to_workstream(
                        workstream_id=workstream_id,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "session_id": active_session_id,
                        "vault_name": active_vault_name,
                        "workstream": workstream.to_dict(),
                    }
                elif op == "update_workstream":
                    _require(workstream_id, "workstream_id is required")
                    store.update_workstream(
                        workstream_id=workstream_id,
                        title=title,
                        status=status,
                        type=type,
                        topic=topic,
                        entities=entities,
                        project=project,
                        objective=objective,
                        strategy=strategy,
                        metadata=metadata,
                    )
                    _maybe_add_artifacts(store, workstream_id, active_vault_name or "", artifacts)
                    indexed_fields = await _maybe_index_workstream_fields(store, workstream_id)
                    workstream = store.get_workstream(workstream_id)
                    result = {
                        "status": "ok",
                        "operation": op,
                        "indexed_fields": indexed_fields,
                        "workstream": workstream.to_dict() if workstream else None,
                    }
                else:
                    return (
                        "Unknown operation. Available: create_workstream, get_workstream, "
                        "search_workstreams, link_session, update_workstream"
                    )
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                return json.dumps(result, ensure_ascii=False, indent=2)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "memory_ops failed",
                    data={
                        "operation": operation,
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                return f"Error performing '{operation}' operation: {exc}"

        return Tool(
            memory_ops,
            name="memory_ops",
            description="Manage workstream memory.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for workstream memory access."""
        return """
Workstream field guidance:
- `title`: compact human-readable label for the workstream.
- `type`: kind of work or deliverable, not the subject matter.
- `topic`: subject/theme of the work; a phrase or sentence is fine.
- `entities`: named people, organizations, funders, clients, places, or other proper nouns.
- `project`: project, program, initiative, client engagement, or internal work area.
- `objective`: outcome the user is trying to accomplish.
- `strategy`: reusable approach, format, style preference, decision, constraint, or tactic.

Update only fields supported by current context. Do not invent specific entities,
projects, or objectives to fill blanks.

Full documentation:
- `__virtual_docs__/tools/memory_ops.md`
"""

    @staticmethod
    def _parse_limit(value: int | str) -> int | str:
        if isinstance(value, int):
            if value <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return value
        normalized = str(value or "").strip().lower()
        if not normalized or normalized == "all":
            return "all"
        if normalized.isdigit():
            parsed = int(normalized)
            if parsed <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return parsed
        raise ValueError("limit must be a positive integer or 'all'")


def _require(value: object, message: str) -> None:
    if value is None:
        raise ValueError(message)
    if isinstance(value, str) and not value.strip():
        raise ValueError(message)


async def _maybe_index_workstream_fields(store: WorkstreamStore, workstream_id: str) -> int:
    try:
        return await store.index_workstream_fields(
            workstream_id=workstream_id,
            vector_service=VectorService(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "workstream_field_indexing_skipped",
            data={
                "workstream_id": workstream_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return 0


def _maybe_add_artifacts(
    store: WorkstreamStore,
    workstream_id: str,
    vault_name: str,
    artifacts: list[dict[str, Any]] | None,
) -> None:
    parsed: list[WorkstreamArtifact] = []
    for raw in artifacts or []:
        path = str(raw.get("path") or "").strip()
        _require(path, "path is required for each artifact")
        parsed.append(
            WorkstreamArtifact(
                path=path,
                artifact_role=str(raw.get("artifact_role") or raw.get("role") or "file_retrieved"),
                vault_name=str(raw.get("vault_name") or vault_name),
                metadata=dict(raw.get("metadata") or {}),
            )
        )
    if parsed:
        store.add_workstream_artifacts(workstream_id=workstream_id, artifacts=tuple(parsed))
