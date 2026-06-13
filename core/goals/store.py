"""SQLite-backed store for goal_ops."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.database import connect_sqlite_from_system_db
from core.goals.schema import DB_NAME, ensure_goal_ops_schema


GOAL_STATUSES = {"active", "paused", "completed", "cancelled", "blocked"}
STEP_STATUSES = {"pending", "in_progress", "completed", "skipped", "blocked", "superseded"}
SUPERSEDED_REPLACE_STATUSES = {"pending", "in_progress", "blocked"}


class _UnsetValue:
    """Sentinel for omitted goal update fields."""


GOAL_FIELD_UNSET = _UnsetValue()


@dataclass(frozen=True)
class GoalRecord:
    goal_id: str
    vault_name: str
    workspace_path_hint: str | None
    title: str
    objective: str
    status: str
    success_criteria: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["success_criteria"] = list(self.success_criteria)
        return payload


@dataclass(frozen=True)
class GoalStepRecord:
    step_id: str
    goal_id: str
    position: int
    title: str
    status: str
    summary: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalEventRecord:
    event_id: str
    goal_id: str
    step_id: str | None
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
    step_id: str | None
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
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create one goal, optional initial steps, and a creation event."""
        clean_vault = _required_text(vault_name, "vault_name")
        clean_title = _required_text(title, "title")
        clean_objective = _required_text(objective, "objective")
        goal_id = _new_id("goal")
        now = _utc_now()
        criteria = _clean_string_list(success_criteria)
        clean_metadata = _clean_dict(metadata)
        clean_workspace = _optional_text(workspace_path_hint)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO goals (
                    goal_id, vault_name, workspace_path_hint, title, objective, status,
                    success_criteria_json, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal_id,
                    clean_vault,
                    clean_workspace,
                    clean_title,
                    clean_objective,
                    "active",
                    _dump_json(list(criteria)),
                    _dump_json(clean_metadata),
                    now,
                    now,
                ),
            )
            inserted_steps = self._insert_steps(conn, goal_id=goal_id, steps=steps or [], now=now)
            self._insert_event(
                conn,
                goal_id=goal_id,
                event_type="created",
                message=f"Created goal: {clean_title}",
                metadata={"initial_step_count": len(inserted_steps)},
                now=now,
            )
            conn.commit()
            return self._goal_payload(conn, goal_id, include_steps=True)

    def update_goal(
        self,
        *,
        goal_id: str,
        title: Any = GOAL_FIELD_UNSET,
        objective: Any = GOAL_FIELD_UNSET,
        status: Any = GOAL_FIELD_UNSET,
        workspace_path_hint: Any = GOAL_FIELD_UNSET,
        success_criteria: Any = GOAL_FIELD_UNSET,
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
            return self._goal_payload(conn, clean_goal_id, include_steps=True)

    def get_goal(self, *, goal_id: str, include_superseded: bool = False) -> dict[str, Any]:
        """Return one goal with steps and latest checkpoint."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        with self._connect() as conn:
            self._require_goal(conn, clean_goal_id)
            return self._goal_payload(
                conn,
                clean_goal_id,
                include_steps=True,
                include_superseded=include_superseded,
            )

    def list_goals(
        self,
        *,
        vault_name: str,
        status: str | None = None,
        workspace_path_hint: str | None = None,
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

    def replace_steps(
        self,
        *,
        goal_id: str,
        steps: list[dict[str, Any]],
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Replace the active step plan in one transaction."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        if not isinstance(steps, list):
            raise ValueError("steps must be a list")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            self._require_goal(conn, clean_goal_id)
            supplied_ids = {
                str(step.get("step_id")).strip()
                for step in steps
                if isinstance(step, dict) and str(step.get("step_id") or "").strip()
            }
            if supplied_ids:
                self._require_steps_belong_to_goal(conn, clean_goal_id, supplied_ids)
            placeholders = ",".join("?" for _ in supplied_ids)
            supersede_params: list[Any] = [now, clean_goal_id, *sorted(SUPERSEDED_REPLACE_STATUSES)]
            not_in_clause = ""
            if supplied_ids:
                not_in_clause = f"AND step_id NOT IN ({placeholders})"
                supersede_params.extend(sorted(supplied_ids))
            conn.execute(
                f"""
                UPDATE goal_steps
                SET status = 'superseded', updated_at = ?
                WHERE goal_id = ?
                  AND status IN ({','.join('?' for _ in SUPERSEDED_REPLACE_STATUSES)})
                  {not_in_clause}
                """,
                supersede_params,
            )
            for index, step in enumerate(steps, start=1):
                self._upsert_step(conn, goal_id=clean_goal_id, step=step, index=index, now=now)
            self._touch_goal(conn, clean_goal_id, now)
            self._insert_event(
                conn,
                goal_id=clean_goal_id,
                event_type="plan_changed",
                message=_optional_text(reason) or "Replaced active goal steps.",
                metadata={"step_count": len(steps)},
                now=now,
            )
            conn.commit()
            return self._goal_payload(conn, clean_goal_id, include_steps=True)

    def update_steps(
        self,
        *,
        goal_id: str,
        updates: list[dict[str, Any]],
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Apply multiple step updates in one transaction."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        if not isinstance(updates, list) or not updates:
            raise ValueError("updates must be a non-empty list")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            self._require_goal(conn, clean_goal_id)
            changed: list[dict[str, Any]] = []
            for update in updates:
                changed.append(self._update_step(conn, clean_goal_id, update, now))
            self._touch_goal(conn, clean_goal_id, now)
            self._insert_event(
                conn,
                goal_id=clean_goal_id,
                event_type="status_changed" if any("status" in item for item in changed) else "plan_changed",
                message=_optional_text(reason) or "Updated goal steps.",
                metadata={"updates": changed},
                now=now,
            )
            conn.commit()
            return self._goal_payload(conn, clean_goal_id, include_steps=True)

    def list_steps(self, *, goal_id: str, include_superseded: bool = False) -> list[dict[str, Any]]:
        clean_goal_id = _required_text(goal_id, "goal_id")
        with self._connect() as conn:
            self._require_goal(conn, clean_goal_id)
            return [
                step.to_dict()
                for step in self._list_steps(
                    conn,
                    clean_goal_id,
                    include_superseded=include_superseded,
                )
            ]

    def add_events(self, *, goal_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clean_goal_id = _required_text(goal_id, "goal_id")
        if not isinstance(events, list) or not events:
            raise ValueError("events must be a non-empty list")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            self._require_goal(conn, clean_goal_id)
            inserted = []
            for event in events:
                inserted.append(
                    self._insert_event(
                        conn,
                        goal_id=clean_goal_id,
                        step_id=_optional_text(event.get("step_id")),
                        event_type=_required_text(event.get("event_type"), "event_type"),
                        message=_required_text(event.get("message"), "message"),
                        metadata=_clean_dict(event.get("metadata")),
                        now=now,
                    )
                )
            self._touch_goal(conn, clean_goal_id, now)
            conn.commit()
            return [event.to_dict() for event in inserted]

    def list_events(self, *, goal_id: str, limit: int = 50) -> list[dict[str, Any]]:
        clean_goal_id = _required_text(goal_id, "goal_id")
        with self._connect() as conn:
            self._require_goal(conn, clean_goal_id)
            rows = conn.execute(
                """
                SELECT *
                FROM goal_events
                WHERE goal_id = ?
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (clean_goal_id, _bounded_limit(limit, maximum=200)),
            ).fetchall()
        return [self._event_from_row(row).to_dict() for row in rows]

    def checkpoint(
        self,
        *,
        goal_id: str,
        summary: str,
        step_id: str | None = None,
        current_state: str | None = None,
        next_actions: list[Any] | tuple[Any, ...] | None = None,
        open_questions: list[Any] | tuple[Any, ...] | None = None,
        risks: list[Any] | tuple[Any, ...] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a checkpoint and compact checkpoint event."""
        clean_goal_id = _required_text(goal_id, "goal_id")
        clean_summary = _required_text(summary, "summary")
        clean_step_id = _optional_text(step_id)
        now = _utc_now()
        checkpoint_id = _new_id("checkpoint")
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            self._require_goal(conn, clean_goal_id)
            if clean_step_id:
                self._require_steps_belong_to_goal(conn, clean_goal_id, {clean_step_id})
            conn.execute(
                """
                INSERT INTO goal_checkpoints (
                    checkpoint_id, goal_id, step_id, summary, current_state,
                    next_actions_json, open_questions_json, risks_json,
                    metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    clean_goal_id,
                    clean_step_id,
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
                step_id=clean_step_id,
                event_type="checkpoint",
                message=clean_summary,
                metadata={"checkpoint_id": checkpoint_id},
                now=now,
            )
            self._touch_goal(conn, clean_goal_id, now)
            conn.commit()
            return self.get_latest_checkpoint(goal_id=clean_goal_id) or {}

    def get_latest_checkpoint(self, *, goal_id: str) -> dict[str, Any] | None:
        clean_goal_id = _required_text(goal_id, "goal_id")
        with self._connect() as conn:
            self._require_goal(conn, clean_goal_id)
            row = conn.execute(
                """
                SELECT *
                FROM goal_checkpoints
                WHERE goal_id = ?
                ORDER BY created_at DESC, checkpoint_id DESC
                LIMIT 1
                """,
                (clean_goal_id,),
            ).fetchone()
        return self._checkpoint_from_row(row).to_dict() if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = connect_sqlite_from_system_db(DB_NAME, self.system_root)
        conn.row_factory = sqlite3.Row
        return conn

    def _goal_payload(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        *,
        include_steps: bool,
        include_superseded: bool = False,
    ) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        if row is None:
            raise ValueError(f"Goal not found: {goal_id}")
        payload = self._goal_from_row(row).to_dict()
        if include_steps:
            payload["steps"] = [
                step.to_dict()
                for step in self._list_steps(
                    conn,
                    goal_id,
                    include_superseded=include_superseded,
                )
            ]
        checkpoint = self._latest_checkpoint_in_conn(conn, goal_id)
        payload["latest_checkpoint"] = checkpoint.to_dict() if checkpoint else None
        return payload

    def _insert_steps(
        self,
        conn: sqlite3.Connection,
        *,
        goal_id: str,
        steps: list[dict[str, Any]],
        now: str,
    ) -> list[GoalStepRecord]:
        inserted = []
        for index, step in enumerate(steps, start=1):
            inserted.append(self._upsert_step(conn, goal_id=goal_id, step=step, index=index, now=now))
        return inserted

    def _upsert_step(
        self,
        conn: sqlite3.Connection,
        *,
        goal_id: str,
        step: dict[str, Any],
        index: int,
        now: str,
    ) -> GoalStepRecord:
        if not isinstance(step, dict):
            raise ValueError("each step must be an object")
        step_id = _optional_text(step.get("step_id")) or _new_id("step")
        position = _parse_position(step.get("position"), index)
        title = _required_text(step.get("title"), "step.title")
        status = _validate_status(str(step.get("status") or "pending"), STEP_STATUSES, "step status")
        summary = _optional_text(step.get("summary"))
        metadata = _clean_dict(step.get("metadata"))
        existing = conn.execute(
            "SELECT step_id, goal_id FROM goal_steps WHERE step_id = ?",
            (step_id,),
        ).fetchone()
        if existing:
            if str(existing["goal_id"]) != goal_id:
                raise ValueError(f"Step id already belongs to a different goal: {step_id}")
            conn.execute(
                """
                UPDATE goal_steps
                SET position = ?, title = ?, status = ?, summary = ?, metadata_json = ?, updated_at = ?
                WHERE step_id = ? AND goal_id = ?
                """,
                (position, title, status, summary, _dump_json(metadata), now, step_id, goal_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO goal_steps (
                    step_id, goal_id, position, title, status, summary,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (step_id, goal_id, position, title, status, summary, _dump_json(metadata), now, now),
            )
        row = conn.execute("SELECT * FROM goal_steps WHERE step_id = ?", (step_id,)).fetchone()
        return self._step_from_row(row)

    def _update_step(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        update: dict[str, Any],
        now: str,
    ) -> dict[str, Any]:
        if not isinstance(update, dict):
            raise ValueError("each step update must be an object")
        step_id = _required_text(update.get("step_id"), "step_id")
        self._require_steps_belong_to_goal(conn, goal_id, {step_id})
        assignments: list[str] = []
        params: list[Any] = []
        changed: dict[str, Any] = {"step_id": step_id}
        if "position" in update:
            value = _parse_position(update.get("position"), None)
            assignments.append("position = ?")
            params.append(value)
            changed["position"] = value
        if "title" in update:
            value = _required_text(update.get("title"), "title")
            assignments.append("title = ?")
            params.append(value)
            changed["title"] = value
        if "status" in update:
            value = _validate_status(str(update.get("status")), STEP_STATUSES, "step status")
            assignments.append("status = ?")
            params.append(value)
            changed["status"] = value
        if "summary" in update:
            value = _optional_text(update.get("summary"))
            assignments.append("summary = ?")
            params.append(value)
            changed["summary"] = value
        if "metadata" in update:
            value = _clean_dict(update.get("metadata"))
            assignments.append("metadata_json = ?")
            params.append(_dump_json(value))
            changed["metadata"] = value
        if len(changed) == 1:
            raise ValueError("step update requires at least one mutable field")
        assignments.append("updated_at = ?")
        params.append(now)
        params.extend([step_id, goal_id])
        conn.execute(
            f"UPDATE goal_steps SET {', '.join(assignments)} WHERE step_id = ? AND goal_id = ?",
            params,
        )
        return changed

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        *,
        goal_id: str,
        event_type: str,
        message: str,
        step_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: str,
    ) -> GoalEventRecord:
        clean_step_id = _optional_text(step_id)
        if clean_step_id:
            self._require_steps_belong_to_goal(conn, goal_id, {clean_step_id})
        event_id = _new_id("event")
        conn.execute(
            """
            INSERT INTO goal_events (
                event_id, goal_id, step_id, event_type, message, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                goal_id,
                clean_step_id,
                _required_text(event_type, "event_type"),
                _required_text(message, "message"),
                _dump_json(_clean_dict(metadata)),
                now,
            ),
        )
        row = conn.execute("SELECT * FROM goal_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._event_from_row(row)

    def _list_steps(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        *,
        include_superseded: bool,
    ) -> list[GoalStepRecord]:
        clause = "" if include_superseded else "AND status != 'superseded'"
        rows = conn.execute(
            f"""
            SELECT *
            FROM goal_steps
            WHERE goal_id = ?
            {clause}
            ORDER BY position ASC, created_at ASC, step_id ASC
            """,
            (goal_id,),
        ).fetchall()
        return [self._step_from_row(row) for row in rows]

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

    def _require_goal(self, conn: sqlite3.Connection, goal_id: str) -> None:
        row = conn.execute("SELECT 1 FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        if row is None:
            raise ValueError(f"Goal not found: {goal_id}")

    def _require_steps_belong_to_goal(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        step_ids: set[str],
    ) -> None:
        if not step_ids:
            return
        placeholders = ",".join("?" for _ in step_ids)
        rows = conn.execute(
            f"""
            SELECT step_id
            FROM goal_steps
            WHERE goal_id = ?
              AND step_id IN ({placeholders})
            """,
            (goal_id, *sorted(step_ids)),
        ).fetchall()
        found = {str(row["step_id"]) for row in rows}
        missing = sorted(step_ids - found)
        if missing:
            raise ValueError(f"Step(s) not found for goal {goal_id}: {', '.join(missing)}")

    def _touch_goal(self, conn: sqlite3.Connection, goal_id: str, now: str) -> None:
        conn.execute("UPDATE goals SET updated_at = ? WHERE goal_id = ?", (now, goal_id))

    @staticmethod
    def _goal_from_row(row: sqlite3.Row) -> GoalRecord:
        return GoalRecord(
            goal_id=str(row["goal_id"]),
            vault_name=str(row["vault_name"]),
            workspace_path_hint=row["workspace_path_hint"],
            title=str(row["title"]),
            objective=str(row["objective"]),
            status=str(row["status"]),
            success_criteria=tuple(_load_json(row["success_criteria_json"], default=[])),
            metadata=_clean_dict(_load_json(row["metadata_json"], default={})),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _step_from_row(row: sqlite3.Row) -> GoalStepRecord:
        return GoalStepRecord(
            step_id=str(row["step_id"]),
            goal_id=str(row["goal_id"]),
            position=int(row["position"]),
            title=str(row["title"]),
            status=str(row["status"]),
            summary=row["summary"],
            metadata=_clean_dict(_load_json(row["metadata_json"], default={})),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> GoalEventRecord:
        return GoalEventRecord(
            event_id=str(row["event_id"]),
            goal_id=str(row["goal_id"]),
            step_id=row["step_id"],
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
            step_id=row["step_id"],
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


def _parse_position(value: Any, index: int | None) -> int:
    if value is None or value == "":
        if index is None:
            raise ValueError("position is required")
        return index * 10
    try:
        position = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("position must be an integer") from exc
    if position <= 0:
        raise ValueError("position must be positive")
    return position


def _bounded_limit(value: Any, *, maximum: int = 100) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = 20
    return max(1, min(maximum, limit))
