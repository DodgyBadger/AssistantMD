"""SQLite-backed store for goal_ops."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from core.database import connect_sqlite_from_system_db
from core.goals.schema import DB_NAME, ensure_goal_ops_schema
from core.vault_state.service import VaultStateService


GOAL_STATUSES = {"active", "paused", "completed", "cancelled", "blocked"}
GOAL_SOURCE_TYPES = {"chat", "workflow", "context"}
PURGEABLE_GOAL_STATUSES = {"completed", "cancelled"}


class _UnsetValue:
    """Sentinel for omitted goal update fields."""


GOAL_FIELD_UNSET = _UnsetValue()


@dataclass(frozen=True)
class GoalRecord:
    goal_id: str
    vault_name: str
    workspace_path_hint: str | None
    source_type: str | None
    source_id: str | None
    source_task_id: str | None
    source_label: str | None
    title: str
    objective: str
    status: str
    success_criteria: tuple[str, ...]
    plan: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["success_criteria"] = list(self.success_criteria)
        return payload


@dataclass(frozen=True)
class GoalEventRecord:
    event_id: str
    goal_id: str
    event_type: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalCheckpointRecord:
    checkpoint_id: str
    goal_id: str
    summary: str
    current_state: str | None
    next_actions: tuple[str, ...]
    open_questions: tuple[str, ...]
    risks: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["next_actions"] = list(self.next_actions)
        payload["open_questions"] = list(self.open_questions)
        payload["risks"] = list(self.risks)
        return payload


class GoalOpsStore:
    """Persistence API for goal_ops."""

    def __init__(self, system_root: str | None = None):
        self.system_root = system_root
        ensure_goal_ops_schema(system_root)

    def create_goal(
        self,
        *,
        vault_name: str,
        title: str,
        objective: str,
        workspace_path_hint: str | None = None,
        success_criteria: list[Any] | tuple[Any, ...] | None = None,
        metadata: dict[str, Any] | None = None,
        plan: Any = None,
        source_type: str | None = None,
        source_id: str | None = None,
        source_task_id: str | None = None,
        source_label: str | None = None,
    ) -> dict[str, Any]:
        """Create one goal and a creation event."""
        clean_vault = _required_text(vault_name, "vault_name")
        clean_title = _required_text(title, "title")
        clean_objective = _required_text(objective, "objective")
        goal_id = _new_id("goal")
        now = _utc_now()
        criteria = _clean_string_list(success_criteria)
        clean_metadata = _clean_dict(metadata)
        clean_plan = _clean_json_value(plan)
        clean_workspace = _optional_text(workspace_path_hint)
        clean_source_type = _optional_source_type(source_type)
        clean_source_id = _optional_text(source_id)
        clean_source_task_id = _optional_text(source_task_id)
        clean_source_label = _optional_text(source_label)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO goals (
                    goal_id, vault_name, workspace_path_hint,
                    source_type, source_id, source_task_id, source_label,
                    title, objective, status,
                    plan_json, success_criteria_json, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal_id,
                    clean_vault,
                    clean_workspace,
                    clean_source_type,
                    clean_source_id,
                    clean_source_task_id,
                    clean_source_label,
                    clean_title,
                    clean_objective,
                    "active",
                    _dump_json(clean_plan),
                    _dump_json(list(criteria)),
                    _dump_json(clean_metadata),
                    now,
                    now,
                ),
            )
            self._insert_event(
                conn,
                goal_id=goal_id,
                event_type="created",
                message=f"Created goal: {clean_title}",
                metadata={
                    "source_type": clean_source_type,
                    "source_id": clean_source_id,
                    "source_task_id": clean_source_task_id,
                },
                now=now,
            )
            conn.commit()
            return self._goal_payload(conn, goal_id)

    def update_goal(
        self,
        *,
        goal_id: str,
        title: Any = GOAL_FIELD_UNSET,
        objective: Any = GOAL_FIELD_UNSET,
        status: Any = GOAL_FIELD_UNSET,
        workspace_path_hint: Any = GOAL_FIELD_UNSET,
        success_criteria: Any = GOAL_FIELD_UNSET,
        plan: Any = GOAL_FIELD_UNSET,
        metadata: Any = GOAL_FIELD_UNSET,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Update one goal."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        now = _utc_now()
        assignments: list[str] = []
        params: list[Any] = []
        changed: dict[str, Any] = {}
        if title is not GOAL_FIELD_UNSET:
            assignments.append("title = ?")
            value = _required_text(title, "title")
            params.append(value)
            changed["title"] = value
        if objective is not GOAL_FIELD_UNSET:
            assignments.append("objective = ?")
            value = _required_text(objective, "objective")
            params.append(value)
            changed["objective"] = value
        if status is not GOAL_FIELD_UNSET:
            assignments.append("status = ?")
            value = _validate_status(str(status), GOAL_STATUSES, "goal status")
            params.append(value)
            changed["status"] = value
        if workspace_path_hint is not GOAL_FIELD_UNSET:
            assignments.append("workspace_path_hint = ?")
            value = _optional_text(workspace_path_hint)
            params.append(value)
            changed["workspace_path_hint"] = value
        if success_criteria is not GOAL_FIELD_UNSET:
            assignments.append("success_criteria_json = ?")
            value = list(_clean_string_list(success_criteria))
            params.append(_dump_json(value))
            changed["success_criteria"] = value
        if plan is not GOAL_FIELD_UNSET:
            assignments.append("plan_json = ?")
            value = _clean_json_value(plan)
            params.append(_dump_json(value))
            changed["plan"] = value
        if metadata is not GOAL_FIELD_UNSET:
            assignments.append("metadata_json = ?")
            value = _clean_dict(metadata)
            params.append(_dump_json(value))
            changed["metadata"] = value
        if not assignments:
            raise ValueError("update_goal requires at least one field to update")
        assignments.append("updated_at = ?")
        params.append(now)
        params.append(clean_goal_id)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            self._require_goal(conn, clean_goal_id)
            conn.execute(
                f"UPDATE goals SET {', '.join(assignments)} WHERE goal_id = ?",
                params,
            )
            self._insert_event(
                conn,
                goal_id=clean_goal_id,
                event_type="status_changed" if "status" in changed else "goal_updated",
                message=_optional_text(reason) or "Updated goal.",
                metadata={"changed": changed},
                now=now,
            )
            conn.commit()
            return self._goal_payload(conn, clean_goal_id)

    def get_goal(self, *, goal_id: str) -> dict[str, Any]:
        """Return one goal with its latest checkpoint."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        with self._connect() as conn:
            self._require_goal(conn, clean_goal_id)
            return self._goal_payload(conn, clean_goal_id)

    def list_goals(
        self,
        *,
        vault_name: str,
        status: str | None = None,
        workspace_path_hint: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List goals for one vault."""
        clean_vault = _required_text(vault_name, "vault_name")
        clauses = ["vault_name = ?"]
        params: list[Any] = [clean_vault]
        if status:
            clauses.append("status = ?")
            params.append(_validate_status(status, GOAL_STATUSES, "goal status"))
        if workspace_path_hint is not None:
            workspace = _optional_text(workspace_path_hint)
            if workspace is None:
                clauses.append("workspace_path_hint IS NULL")
            else:
                clauses.append("workspace_path_hint = ?")
                params.append(workspace)
        if source_type:
            clauses.append("source_type = ?")
            params.append(_validate_status(source_type, GOAL_SOURCE_TYPES, "goal source_type"))
        if source_id:
            clauses.append("source_id = ?")
            params.append(_required_text(source_id, "source_id"))
        if query:
            clauses.append("(title LIKE ? OR objective LIKE ?)")
            like = f"%{query.strip()}%"
            params.extend([like, like])
        params.append(_bounded_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM goals
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, created_at DESC, goal_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._goal_from_row(row).to_dict() for row in rows]

    def checkpoint(
        self,
        *,
        goal_id: str,
        summary: str,
        current_state: str | None = None,
        next_actions: list[Any] | tuple[Any, ...] | None = None,
        open_questions: list[Any] | tuple[Any, ...] | None = None,
        risks: list[Any] | tuple[Any, ...] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a checkpoint and compact checkpoint event."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        clean_summary = _required_text(summary, "summary")
        now = _utc_now()
        checkpoint_id = _new_id("checkpoint")
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            self._require_goal(conn, clean_goal_id)
            conn.execute(
                """
                INSERT INTO goal_checkpoints (
                    checkpoint_id, goal_id, summary, current_state,
                    next_actions_json, open_questions_json, risks_json,
                    metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    clean_goal_id,
                    clean_summary,
                    _optional_text(current_state),
                    _dump_json(list(_clean_string_list(next_actions))),
                    _dump_json(list(_clean_string_list(open_questions))),
                    _dump_json(list(_clean_string_list(risks))),
                    _dump_json(_clean_dict(metadata)),
                    now,
                ),
            )
            self._insert_event(
                conn,
                goal_id=clean_goal_id,
                event_type="checkpoint",
                message=clean_summary,
                metadata={"checkpoint_id": checkpoint_id},
                now=now,
            )
            self._touch_goal(conn, clean_goal_id, now)
            conn.commit()
            checkpoint = self._latest_checkpoint_in_conn(conn, clean_goal_id)
            return checkpoint.to_dict() if checkpoint else {}

    def list_activity(
        self,
        *,
        goal_id: str,
        step_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return vault mutation activity associated with one goal context."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        with self._connect() as conn:
            goal = self._goal_from_row(self._require_goal(conn, clean_goal_id))
        groups = VaultStateService().list_task_mutations(
            vault_name=goal.vault_name,
            limit=_bounded_limit(limit),
            goal_id=clean_goal_id,
            step_id=_optional_text(step_id),
        )
        return [_mutation_group_to_dict(group) for group in groups]

    def purge_goals(
        self,
        *,
        vault_name: str,
        statuses: list[str] | tuple[str, ...],
        older_than_days: int | None = None,
    ) -> int:
        """Delete purgeable goals for one vault and return the deleted count."""
        clean_vault = _required_text(vault_name, "vault_name")
        clean_statuses = tuple(
            _validate_status(str(status), PURGEABLE_GOAL_STATUSES, "purge goal status")
            for status in statuses
        )
        if not clean_statuses:
            raise ValueError("At least one purge goal status is required")

        clauses = ["vault_name = ?"]
        params: list[Any] = [clean_vault]
        placeholders = ", ".join("?" for _ in clean_statuses)
        clauses.append(f"status IN ({placeholders})")
        params.extend(clean_statuses)

        if older_than_days is not None:
            if older_than_days < 0:
                raise ValueError("older_than_days must be zero or greater")
            cutoff = datetime.now(UTC).replace(microsecond=0) - timedelta(days=older_than_days)
            clauses.append("updated_at < ?")
            params.append(cutoff.isoformat())

        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                f"DELETE FROM goals WHERE {' AND '.join(clauses)}",
                params,
            )
            conn.commit()
            return max(cursor.rowcount, 0)

    def _connect(self) -> sqlite3.Connection:
        conn = connect_sqlite_from_system_db(DB_NAME, self.system_root)
        conn.row_factory = sqlite3.Row
        return conn

    def _goal_payload(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
    ) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        if row is None:
            raise ValueError(f"Goal not found: {goal_id}")
        payload = self._goal_from_row(row).to_dict()
        checkpoint = self._latest_checkpoint_in_conn(conn, goal_id)
        payload["latest_checkpoint"] = checkpoint.to_dict() if checkpoint else None
        return payload

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        *,
        goal_id: str,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        now: str,
    ) -> GoalEventRecord:
        event_id = _new_id("event")
        conn.execute(
            """
            INSERT INTO goal_events (
                event_id, goal_id, event_type, message, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                goal_id,
                _required_text(event_type, "event_type"),
                _required_text(message, "message"),
                _dump_json(_clean_dict(metadata)),
                now,
            ),
        )
        row = conn.execute("SELECT * FROM goal_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._event_from_row(row)

    def _latest_checkpoint_in_conn(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
    ) -> GoalCheckpointRecord | None:
        row = conn.execute(
            """
            SELECT *
            FROM goal_checkpoints
            WHERE goal_id = ?
            ORDER BY created_at DESC, checkpoint_id DESC
            LIMIT 1
            """,
            (goal_id,),
        ).fetchone()
        return self._checkpoint_from_row(row) if row else None

    def _require_goal(self, conn: sqlite3.Connection, goal_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        if row is None:
            raise ValueError(f"Goal not found: {goal_id}")
        return row

    def _touch_goal(self, conn: sqlite3.Connection, goal_id: str, now: str) -> None:
        conn.execute("UPDATE goals SET updated_at = ? WHERE goal_id = ?", (now, goal_id))

    @staticmethod
    def _goal_from_row(row: sqlite3.Row) -> GoalRecord:
        return GoalRecord(
            goal_id=str(row["goal_id"]),
            vault_name=str(row["vault_name"]),
            workspace_path_hint=row["workspace_path_hint"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            source_task_id=row["source_task_id"],
            source_label=row["source_label"],
            title=str(row["title"]),
            objective=str(row["objective"]),
            status=str(row["status"]),
            plan=_load_json(row["plan_json"], default=None),
            success_criteria=tuple(_load_json(row["success_criteria_json"], default=[])),
            metadata=_clean_dict(_load_json(row["metadata_json"], default={})),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> GoalEventRecord:
        return GoalEventRecord(
            event_id=str(row["event_id"]),
            goal_id=str(row["goal_id"]),
            event_type=str(row["event_type"]),
            message=str(row["message"]),
            metadata=_clean_dict(_load_json(row["metadata_json"], default={})),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _checkpoint_from_row(row: sqlite3.Row) -> GoalCheckpointRecord:
        return GoalCheckpointRecord(
            checkpoint_id=str(row["checkpoint_id"]),
            goal_id=str(row["goal_id"]),
            summary=str(row["summary"]),
            current_state=row["current_state"],
            next_actions=tuple(_clean_string_list(_load_json(row["next_actions_json"], default=[]))),
            open_questions=tuple(_clean_string_list(_load_json(row["open_questions_json"], default=[]))),
            risks=tuple(_clean_string_list(_load_json(row["risks_json"], default=[]))),
            metadata=_clean_dict(_load_json(row["metadata_json"], default={})),
            created_at=str(row["created_at"]),
        )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _required_text(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return tuple()
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of strings")
    cleaned = []
    for item in value:
        text = _optional_text(item)
        if text:
            cleaned.append(text)
    return tuple(cleaned)


def _clean_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return dict(value)


def _clean_json_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected a JSON-serializable value") from exc
    return value


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: Any, *, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _validate_status(value: str, allowed: set[str], label: str) -> str:
    status = _required_text(value, label).lower()
    if status not in allowed:
        raise ValueError(f"Invalid {label}: {status}. Expected one of: {', '.join(sorted(allowed))}")
    return status


def _optional_source_type(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    return _validate_status(text, GOAL_SOURCE_TYPES, "goal source_type")


def _bounded_limit(value: Any, *, maximum: int = 100) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = 20
    return max(1, min(maximum, limit))


def _mutation_group_to_dict(group) -> dict[str, Any]:
    return {
        "activity_id": group.activity_id,
        "activity_kind": group.activity_kind,
        "activity_label": group.activity_label,
        "task_id": group.task_id,
        "task_kind": group.task_kind,
        "task_source": group.task_source,
        "task_scope": group.task_scope,
        "task_label": group.task_label,
        "goal_id": group.goal_id,
        "step_id": group.step_id,
        "vault_id": group.vault_id,
        "vault_name": group.vault_name,
        "mutation_count": group.mutation_count,
        "first_mutation_at": group.first_mutation_at.isoformat(),
        "last_mutation_at": group.last_mutation_at.isoformat(),
        "mutations": [
            {
                "id": mutation.id,
                "task_id": mutation.task_id,
                "task_kind": mutation.task_kind,
                "task_source": mutation.task_source,
                "task_scope": mutation.task_scope,
                "task_label": mutation.task_label,
                "goal_id": mutation.goal_id,
                "step_id": mutation.step_id,
                "path": mutation.path,
                "related_path": mutation.related_path,
                "operation": mutation.operation,
                "event_sequence": mutation.event_sequence,
                "before_exists": mutation.before_exists,
                "after_exists": mutation.after_exists,
                "created_at": mutation.created_at.isoformat(),
            }
            for mutation in group.mutations
        ],
    }
