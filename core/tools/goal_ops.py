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
            include_superseded: bool = False,
            workspace_path_hint: str = "",
            data: dict[str, Any] | None = None,
        ):
            """Create, inspect, and update durable goal state.

            :param operation: Operation name.
            :param goal_id: Goal id for goal-specific operations.
            :param status: Optional goal status filter for list_goals.
            :param query: Optional title/objective search for list_goals.
            :param limit: Optional result limit for list_goals/list_events.
            :param include_superseded: Include superseded steps when listing goal steps.
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
                    include_superseded=include_superseded,
                    workspace_path_hint=workspace_path_hint,
                    data=payload,
                )
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
            description="Track durable goals, ordered steps, events, and checkpoints.",
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
        include_superseded: bool,
        workspace_path_hint: str,
        data: dict[str, Any],
    ) -> Any:
        if operation == "create_goal":
            return store.create_goal(
                vault_name=vault_name,
                title=data.get("title"),
                objective=data.get("objective"),
                workspace_path_hint=data.get("workspace_path_hint"),
                success_criteria=data.get("success_criteria"),
                metadata=data.get("metadata"),
                steps=data.get("steps"),
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
                metadata=data.get("metadata") if "metadata" in data else GOAL_FIELD_UNSET,
                reason=data.get("reason"),
            )
        if operation == "get_goal":
            return store.get_goal(
                goal_id=_goal_id(goal_id, data),
                include_superseded=include_superseded or bool(data.get("include_superseded")),
            )
        if operation == "list_goals":
            return store.list_goals(
                vault_name=vault_name,
                status=_optional_filter_text(status or data.get("status")),
                workspace_path_hint=(
                    workspace_path_hint
                    if workspace_path_hint
                    else data.get("workspace_path_hint")
                    if "workspace_path_hint" in data
                    else None
                ),
                query=_optional_filter_text(query or data.get("query")),
                limit=_limit(limit, data, default=20),
            )
        if operation == "replace_steps":
            return store.replace_steps(
                goal_id=_goal_id(goal_id, data),
                steps=_required_list(data.get("steps"), "steps"),
                reason=data.get("reason"),
            )
        if operation == "update_steps":
            return store.update_steps(
                goal_id=_goal_id(goal_id, data),
                updates=_required_list(data.get("updates"), "updates"),
                reason=data.get("reason"),
            )
        if operation == "list_steps":
            return store.list_steps(
                goal_id=_goal_id(goal_id, data),
                include_superseded=include_superseded or bool(data.get("include_superseded")),
            )
        if operation == "add_events":
            return store.add_events(
                goal_id=_goal_id(goal_id, data),
                events=_required_list(data.get("events"), "events"),
            )
        if operation == "list_events":
            return store.list_events(
                goal_id=_goal_id(goal_id, data),
                limit=_limit(limit, data, default=50),
            )
        if operation == "checkpoint":
            return store.checkpoint(
                goal_id=_goal_id(goal_id, data),
                step_id=data.get("step_id"),
                summary=data.get("summary"),
                current_state=data.get("current_state"),
                next_actions=data.get("next_actions"),
                open_questions=data.get("open_questions"),
                risks=data.get("risks"),
                metadata=data.get("metadata"),
            )
        if operation == "get_latest_checkpoint":
            return store.get_latest_checkpoint(goal_id=_goal_id(goal_id, data))
        raise ValueError(
            "operation must be one of: create_goal, update_goal, get_goal, list_goals, "
            "replace_steps, update_steps, list_steps, add_events, list_events, checkpoint, "
            "get_latest_checkpoint"
        )

    @staticmethod
    def _resolve_vault_name(ctx: RunContext, vault_path: str | None) -> str:
        deps = getattr(ctx, "deps", None)
        vault_name = str(getattr(deps, "vault_name", "") or "").strip()
        if vault_name:
            return vault_name
        if vault_path:
            return Path(vault_path).name
        raise ValueError("goal_ops requires active vault context")


def _goal_id(goal_id: str, data: dict[str, Any]) -> str:
    resolved = str(goal_id or data.get("goal_id") or "").strip()
    if not resolved:
        raise ValueError("goal_id is required")
    return resolved


def _required_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return value


def _optional_filter_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _limit(value: int | str, data: dict[str, Any], *, default: int) -> int:
    raw = value if value != "" else data.get("limit", default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
