"""Goal operations tool."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.goals.store import GOAL_FIELD_UNSET, GoalOpsStore
from core.logger import UnifiedLogger
from core.runtime.execution_tasks import get_current_execution_task
from core.tools.failures import FailureClassification, tool_failure_return

from .base import BaseTool

logger = UnifiedLogger(tag="goal-ops-tool")


class GoalOps(BaseTool):
    """Create, inspect, and update durable goal_ops records."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the goal_ops tool."""

        async def goal_ops(
            ctx: RunContext,
            *,
            operation: str,
            goal_id: str = "",
            status: str = "",
            query: str = "",
            limit: int | str = "",
            workspace_path_hint: str = "",
            data: dict[str, Any] | None = None,
        ):
            """Create, inspect, and update durable goal state.

            :param operation: Operation name.
            :param goal_id: Goal id for goal-specific operations.
            :param status: Optional goal status filter for list_goals.
            :param query: Optional title/objective search for list_goals.
            :param limit: Optional result limit for list_goals.
            :param workspace_path_hint: Optional non-authoritative workspace hint filter.
            :param data: Operation-specific payload.
            """
            op = (operation or "").strip().lower()
            payload = data or {}
            try:
                vault_name = cls._resolve_vault_name(ctx, vault_path)
                store = GoalOpsStore()
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "goal_ops", "operation": op, "vault": vault_name},
                )
                result = cls._dispatch(
                    store,
                    operation=op,
                    vault_name=vault_name,
                    goal_id=goal_id,
                    status=status,
                    query=query,
                    limit=limit,
                    workspace_path_hint=workspace_path_hint,
                    data=payload,
                    ctx=ctx,
                )
                cls._log_success(operation=op, vault_name=vault_name, result=result)
                return json.dumps(
                    {"status": "ok", "operation": op, "result": result},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            except ValueError as exc:
                return tool_failure_return(
                    tool_name="goal_ops",
                    message="goal_ops could not complete the requested operation",
                    classification=FailureClassification(
                        failure_kind="permanent",
                        retryable=False,
                        phase="tool_execution",
                        message=str(exc),
                        suggested_action="Adjust the goal_ops operation or payload before trying again.",
                    ),
                    metadata={"operation": op},
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "goal_ops execution failed",
                    data={
                        "operation": op,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                return tool_failure_return(
                    tool_name="goal_ops",
                    message="goal_ops encountered an unexpected failure",
                    classification=FailureClassification(
                        failure_kind="unknown",
                        retryable=False,
                        phase="tool_execution",
                        message=str(exc),
                        suggested_action="Inspect the goal_ops payload and retry only after correcting the cause.",
                    ),
                    metadata={"operation": op},
                )

        return Tool(
            goal_ops,
            name="goal_ops",
            description="Track durable goals and compact recovery checkpoints.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get minimal compatibility instructions for goal_ops."""
        return """
Full documentation:
- `__virtual_docs__/tools/goal_ops.md`
"""

    @classmethod
    def _dispatch(
        cls,
        store: GoalOpsStore,
        *,
        operation: str,
        vault_name: str,
        goal_id: str,
        status: str,
        query: str,
        limit: int | str,
        workspace_path_hint: str,
        data: dict[str, Any],
        ctx: RunContext,
    ) -> Any:
        if operation == "create_goal":
            source = cls._infer_source(ctx)
            return store.create_goal(
                vault_name=vault_name,
                title=data.get("title"),
                objective=data.get("objective"),
                workspace_path_hint=data.get("workspace_path_hint"),
                success_criteria=data.get("success_criteria"),
                metadata=data.get("metadata"),
                plan=data.get("plan"),
                source_type=source["source_type"],
                source_id=source["source_id"],
                source_task_id=source["source_task_id"],
                source_label=source["source_label"],
            )
        if operation == "update_goal":
            return store.update_goal(
                goal_id=_goal_id(goal_id, data),
                title=data.get("title") if "title" in data else GOAL_FIELD_UNSET,
                objective=data.get("objective") if "objective" in data else GOAL_FIELD_UNSET,
                status=data.get("status") if "status" in data else GOAL_FIELD_UNSET,
                workspace_path_hint=(
                    data.get("workspace_path_hint")
                    if "workspace_path_hint" in data
                    else GOAL_FIELD_UNSET
                ),
                success_criteria=(
                    data.get("success_criteria")
                    if "success_criteria" in data
                    else GOAL_FIELD_UNSET
                ),
                plan=data.get("plan") if "plan" in data else GOAL_FIELD_UNSET,
                metadata=data.get("metadata") if "metadata" in data else GOAL_FIELD_UNSET,
                reason=data.get("reason"),
            )
        if operation == "get_goal":
            return store.get_goal(goal_id=_goal_id(goal_id, data))
        if operation == "list_goals":
            source_filter = cls._resolve_list_source_filter(ctx, data)
            return store.list_goals(
                vault_name=vault_name,
                status=_optional_status_filter(status or data.get("status")),
                workspace_path_hint=(
                    workspace_path_hint
                    if workspace_path_hint
                    else data.get("workspace_path_hint")
                    if "workspace_path_hint" in data
                    else None
                ),
                source_type=source_filter["source_type"],
                source_id=source_filter["source_id"],
                query=_optional_filter_text(query or data.get("query")),
                limit=_limit(limit, data, default=20),
            )
        if operation == "checkpoint":
            return store.checkpoint(
                goal_id=_goal_id(goal_id, data),
                summary=data.get("summary"),
                current_state=data.get("current_state"),
                next_actions=data.get("next_actions"),
                open_questions=data.get("open_questions"),
                risks=data.get("risks"),
                metadata=data.get("metadata"),
            )
        if operation == "list_activity":
            return store.list_activity(
                goal_id=_goal_id(goal_id, data),
                limit=_limit(limit, data, default=20),
            )
        raise ValueError(
            "operation must be one of: create_goal, update_goal, get_goal, list_goals, "
            "checkpoint, list_activity"
        )

    @staticmethod
    def _log_success(*, operation: str, vault_name: str, result: Any) -> None:
        if operation not in {"create_goal", "update_goal", "checkpoint"}:
            return
        if not isinstance(result, dict):
            return

        goal_id = _optional_filter_text(result.get("goal_id"))
        if not goal_id:
            return

        event_by_operation = {
            "create_goal": "goal_ops_goal_created",
            "update_goal": "goal_ops_goal_updated",
            "checkpoint": "goal_ops_checkpoint_created",
        }
        data = {
            "event": event_by_operation[operation],
            "status": "completed",
            "tool": "goal_ops",
            "operation": operation,
            "vault_name": vault_name,
            "goal_id": goal_id,
        }
        goal_status = _optional_filter_text(result.get("status"))
        if goal_status:
            data["goal_status"] = goal_status
        checkpoint_id = _optional_filter_text(result.get("checkpoint_id"))
        if checkpoint_id:
            data["checkpoint_id"] = checkpoint_id
        source_type = _optional_filter_text(result.get("source_type"))
        if source_type:
            data["source_type"] = source_type
        source_id = _optional_filter_text(result.get("source_id"))
        if source_id:
            data["source_id"] = source_id
        source_task_id = _optional_filter_text(result.get("source_task_id"))
        if source_task_id:
            data["source_task_id"] = source_task_id

        logger.add_sink("validation").info(data["event"], data=data)

    @staticmethod
    def _resolve_vault_name(ctx: RunContext, vault_path: str | None) -> str:
        deps = getattr(ctx, "deps", None)
        vault_name = str(getattr(deps, "vault_name", "") or "").strip()
        if vault_name:
            return vault_name
        if vault_path:
            return Path(vault_path).name
        raise ValueError("goal_ops requires active vault context")

    @staticmethod
    def _infer_source(ctx: RunContext) -> dict[str, str | None]:
        deps = getattr(ctx, "deps", None)
        authoring_workflow_id = str(getattr(deps, "authoring_workflow_id", "") or "").strip()
        session_id = str(getattr(deps, "session_id", "") or "").strip()
        current_task = get_current_execution_task()
        source_task_id = current_task.task_id if current_task is not None else None

        if authoring_workflow_id:
            source_type = "context" if "/context/" in authoring_workflow_id else "workflow"
            return {
                "source_type": source_type,
                "source_id": authoring_workflow_id,
                "source_task_id": source_task_id,
                "source_label": authoring_workflow_id,
            }
        if session_id:
            return {
                "source_type": "chat",
                "source_id": session_id,
                "source_task_id": source_task_id,
                "source_label": f"chat:{session_id}",
            }
        return {
            "source_type": None,
            "source_id": None,
            "source_task_id": source_task_id,
            "source_label": None,
        }

    @staticmethod
    def _resolve_list_source_filter(ctx: RunContext, data: dict[str, Any]) -> dict[str, str | None]:
        source = _optional_filter_text(data.get("source"))
        if source is None:
            return {"source_type": None, "source_id": None}
        if source == "current_session":
            deps = getattr(ctx, "deps", None)
            session_id = str(getattr(deps, "session_id", "") or "").strip()
            if not session_id:
                raise ValueError("list_goals source='current_session' requires an active chat session")
            return {"source_type": "chat", "source_id": session_id}
        if source == "session":
            session_id = _optional_filter_text(data.get("session_id"))
            if not session_id:
                raise ValueError("list_goals source='session' requires data.session_id")
            return {"source_type": "chat", "source_id": session_id}
        raise ValueError("list_goals source must be one of: current_session, session")


def _goal_id(goal_id: str, data: dict[str, Any]) -> str:
    resolved = str(goal_id or data.get("goal_id") or "").strip()
    if not resolved:
        raise ValueError("goal_id is required")
    return resolved


def _optional_filter_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_status_filter(value: Any) -> str | None:
    text = _optional_filter_text(value)
    if text is None or text.lower() == "any":
        return None
    return text


def _limit(value: int | str, data: dict[str, Any], *, default: int) -> int:
    raw = value if value != "" else data.get("limit", default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
