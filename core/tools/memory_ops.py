"""Work episode memory operations tool."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.memory import MemoryContext
from core.memory.work_episodes import (
    WorkEpisodeArtifact,
    WorkEpisodeField,
    WorkEpisodeStore,
    normalize_field_value,
)

from .base import BaseTool


logger = UnifiedLogger(tag="memory-ops-tool")


class MemoryOps(BaseTool):
    """Manage work episode memory."""

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
            episode_id: str = "",
            related_episode_id: str = "",
            title: str = "",
            status: str = "active",
            field_type: str = "",
            value: str = "",
            fields: list[dict[str, Any]] | None = None,
            artifacts: list[dict[str, Any]] | None = None,
            metadata: dict[str, Any] | None = None,
            link_source: str = "tool",
            confidence: float = 0.5,
            action: str = "",
            reason: str = "",
        ) -> str:
            """Manage work episode memory.

            :param operation: Operation name.
            :param session_id: Optional explicit session id. Defaults to the active session when available.
            :param vault_name: Optional explicit vault name. Defaults to active vault when available.
            :param limit: Positive integer or "all"
            :param episode_id: Work episode id for episode operations.
            :param related_episode_id: Related episode id for feedback operations.
            :param title: Episode title for create/update operations.
            :param status: Episode status for create operations.
            :param field_type: Single field type for search/update operations.
            :param value: Single field value for search/update operations.
            :param fields: Optional list of field objects.
            :param artifacts: Optional list of artifact objects.
            :param metadata: Optional object metadata for create operations.
            :param link_source: Source label for session-episode links.
            :param confidence: Confidence for link/field operations.
            :param action: Feedback action.
            :param reason: Optional feedback reason.
            """
            try:
                deps = getattr(ctx, "deps", None)
                requested_session_id = str(session_id or "").strip() or None
                requested_vault_name = str(vault_name or "").strip() or None
                op = (operation or "").strip().lower()
                memory_context = MemoryContext.from_deps(deps)
                active_session_id = requested_session_id or memory_context.session_id
                active_vault_name = requested_vault_name or memory_context.vault_name
                store = WorkEpisodeStore()

                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "memory_ops",
                        "operation": op,
                    },
                )

                resolved_limit = cls._parse_limit(limit)
                if op == "current_episode":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    episode = store.get_current_episode(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    result = {
                        "status": "linked" if episode else "unlinked",
                        "operation": op,
                        "vault_name": active_vault_name,
                        "session_id": active_session_id,
                        "episode": episode.to_dict() if episode else None,
                    }
                elif op == "create_episode":
                    _require(active_vault_name, "vault_name is required")
                    episode = store.create_episode(
                        vault_name=active_vault_name,
                        title=title or None,
                        episode_id=episode_id or None,
                        status=status or "active",
                        confidence=float(confidence),
                        metadata=metadata or {},
                    )
                    _maybe_update_fields(store, episode.episode_id, fields, field_type, value, confidence)
                    _maybe_add_artifacts(store, episode.episode_id, active_vault_name, artifacts)
                    result = {
                        "status": "ok",
                        "operation": op,
                        "episode": store.get_episode(episode.episode_id).to_dict(),
                    }
                elif op == "get_episode":
                    _require(episode_id, "episode_id is required")
                    episode = store.get_episode(episode_id)
                    result = {
                        "status": "found" if episode else "not_found",
                        "operation": op,
                        "episode": episode.to_dict() if episode else None,
                    }
                elif op == "search_episodes":
                    _require(active_vault_name, "vault_name is required")
                    normalized_value = normalize_field_value(value) if field_type and value else None
                    episodes = store.search_episodes(
                        vault_name=active_vault_name,
                        field_type=field_type or None,
                        normalized_value=normalized_value,
                        limit=resolved_limit if isinstance(resolved_limit, int) else 20,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "episodes": [episode.to_dict() for episode in episodes],
                    }
                elif op == "related_episodes":
                    _require(active_vault_name, "vault_name is required")
                    resolved_episode_id = episode_id
                    if not resolved_episode_id:
                        _require(active_session_id, "session_id or episode_id is required")
                        current = store.get_current_episode(
                            vault_name=active_vault_name,
                            session_id=active_session_id,
                        )
                        resolved_episode_id = current.episode_id if current else ""
                    _require(resolved_episode_id, "episode_id is required")
                    candidates = store.related_episode_candidates(
                        vault_name=active_vault_name,
                        episode_id=resolved_episode_id,
                        limit=resolved_limit if isinstance(resolved_limit, int) else 10,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "episode_id": resolved_episode_id,
                        "candidates": [candidate.to_dict() for candidate in candidates],
                    }
                elif op == "episode_artifacts":
                    _require(episode_id, "episode_id is required")
                    result = {
                        "status": "ok",
                        "operation": op,
                        "episode_id": episode_id,
                        "artifacts": [
                            artifact.to_dict()
                            for artifact in store.list_episode_artifacts(episode_id)
                        ],
                    }
                elif op in {"link_session", "relink_session"}:
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    _require(episode_id, "episode_id is required")
                    episode = store.link_session_to_episode(
                        episode_id=episode_id,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        link_source=link_source or op,
                        confidence=float(confidence),
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "session_id": active_session_id,
                        "vault_name": active_vault_name,
                        "episode": episode.to_dict(),
                    }
                elif op == "unlink_session":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    store.unlink_session_from_episode(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "session_id": active_session_id,
                        "vault_name": active_vault_name,
                    }
                elif op == "update_episode":
                    _require(episode_id, "episode_id is required")
                    _maybe_update_fields(store, episode_id, fields, field_type, value, confidence)
                    episode = store.get_episode(episode_id)
                    result = {
                        "status": "ok",
                        "operation": op,
                        "episode": episode.to_dict() if episode else None,
                    }
                elif op == "record_feedback":
                    _require(episode_id, "episode_id is required")
                    _require(related_episode_id, "related_episode_id is required")
                    _require(action, "action is required")
                    store.record_feedback(
                        current_episode_id=episode_id,
                        related_episode_id=related_episode_id,
                        action=action,
                        reason=reason or None,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "episode_id": episode_id,
                        "related_episode_id": related_episode_id,
                        "action": action,
                    }
                else:
                    return (
                        "Unknown operation. Available: current_episode, create_episode, "
                        "get_episode, search_episodes, "
                        "related_episodes, episode_artifacts, link_session, relink_session, "
                        "unlink_session, update_episode, record_feedback"
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
            description="Manage work episode memory.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for work episode memory access."""
        return """
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


def _maybe_update_fields(
    store: WorkEpisodeStore,
    episode_id: str,
    fields: list[dict[str, Any]] | None,
    field_type: str,
    value: str,
    confidence: float,
) -> None:
    parsed: list[WorkEpisodeField] = []
    for raw in fields or []:
        parsed.append(_field_from_mapping(raw, fallback_confidence=confidence))
    if field_type and value:
        parsed.append(
            WorkEpisodeField(
                field_type=field_type,
                value=value,
                normalized_value=normalize_field_value(value),
                confidence=float(confidence),
                source="tool",
            )
        )
    if parsed:
        store.update_episode_fields(episode_id=episode_id, fields=tuple(parsed))


def _field_from_mapping(raw: dict[str, Any], *, fallback_confidence: float) -> WorkEpisodeField:
    field_type = str(raw.get("field_type") or raw.get("type") or "").strip()
    value = str(raw.get("value") or "").strip()
    _require(field_type, "field_type is required for each field")
    _require(value, "value is required for each field")
    normalized_value = str(raw.get("normalized_value") or "").strip() or normalize_field_value(value)
    return WorkEpisodeField(
        field_type=field_type,
        value=value,
        normalized_value=normalized_value,
        confidence=float(raw.get("confidence", fallback_confidence)),
        source=str(raw.get("source") or "tool"),
    )


def _maybe_add_artifacts(
    store: WorkEpisodeStore,
    episode_id: str,
    vault_name: str,
    artifacts: list[dict[str, Any]] | None,
) -> None:
    parsed: list[WorkEpisodeArtifact] = []
    for raw in artifacts or []:
        path = str(raw.get("path") or "").strip()
        _require(path, "path is required for each artifact")
        parsed.append(
            WorkEpisodeArtifact(
                path=path,
                artifact_role=str(raw.get("artifact_role") or raw.get("role") or "file_retrieved"),
                source=str(raw.get("source") or "tool"),
                vault_name=str(raw.get("vault_name") or vault_name),
                metadata=dict(raw.get("metadata") or {}),
            )
        )
    if parsed:
        store.add_episode_artifacts(episode_id=episode_id, artifacts=tuple(parsed))
