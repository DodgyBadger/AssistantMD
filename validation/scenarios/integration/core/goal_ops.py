"""Integration scenario for goal_ops persistence and tool behavior."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.authoring.shared.tool_binding import resolve_tool_binding
from core.goals import GoalOpsStore
from core.system_migrations import get_system_migration_status
from validation.core.base_scenario import BaseScenario


class GoalOpsScenario(BaseScenario):
    """Validate durable goal_ops operations and batch step semantics."""

    async def test_scenario(self):
        vault = self.create_vault("GoalOpsVault")
        await self.start_system()

        binding = resolve_tool_binding(["goal_ops"], vault_path=str(vault))
        self.soft_assert_equal(binding.tool_names(), ["goal_ops"], "goal_ops should bind through the tool registry")
        tool = binding.tool_specs[0].tool_function
        ctx = SimpleNamespace(deps=SimpleNamespace(vault_name=vault.name))

        create_payload = await tool.function(
            ctx,
            operation="create_goal",
            data={
                "title": "Prepare renewal briefing",
                "objective": "Create a concise renewal briefing from project notes.",
                "workspace_path_hint": "Clients/Acme",
                "success_criteria": ["Draft exists", "Open questions listed"],
                "steps": [
                    {"title": "Review notes"},
                    {"title": "Extract risks"},
                    {"title": "Draft briefing"},
                ],
            },
        )
        created = self._tool_payload(create_payload)
        goal = created["result"]
        goal_id = goal["goal_id"]
        self.soft_assert(goal_id.startswith("goal_"), "create_goal should return a stable goal id")
        self.soft_assert_equal(goal["vault_name"], vault.name, "Goal should be scoped to the active vault")
        self.soft_assert_equal(
            goal["workspace_path_hint"],
            "Clients/Acme",
            "Workspace should be stored as a non-authoritative hint",
        )
        self.soft_assert_equal(
            [step["position"] for step in goal["steps"]],
            [10, 20, 30],
            "Initial steps should get sparse positions from array order",
        )

        replace_payload = await tool.function(
            ctx,
            operation="replace_steps",
            goal_id=goal_id,
            data={
                "reason": "User simplified the plan.",
                "steps": [
                    {"title": "Draft briefing", "position": 30},
                    {"title": "Review source notes", "position": 10},
                    {"title": "List open questions", "position": 20},
                ],
            },
        )
        replaced = self._tool_payload(replace_payload)["result"]
        active_steps = replaced["steps"]
        self.soft_assert_equal(
            [step["title"] for step in active_steps],
            ["Review source notes", "List open questions", "Draft briefing"],
            "replace_steps should return steps ordered by explicit position",
        )
        self.soft_assert_equal(
            len(self._superseded_step_rows(goal_id)),
            3,
            "replace_steps should mark removed active steps superseded rather than deleting them",
        )

        first_step_id = active_steps[0]["step_id"]
        second_step_id = active_steps[1]["step_id"]
        update_payload = await tool.function(
            ctx,
            operation="update_steps",
            goal_id=goal_id,
            data={
                "reason": "Source review finished.",
                "updates": [
                    {"step_id": first_step_id, "status": "completed"},
                    {"step_id": second_step_id, "status": "in_progress", "position": 15},
                ],
            },
        )
        updated_steps = self._tool_payload(update_payload)["result"]["steps"]
        self.soft_assert_equal(
            [(step["title"], step["status"], step["position"]) for step in updated_steps],
            [
                ("Review source notes", "completed", 10),
                ("List open questions", "in_progress", 15),
                ("Draft briefing", "pending", 30),
            ],
            "update_steps should batch status and order changes while keeping completed steps in the ordered plan",
        )
        completed = GoalOpsStore().list_steps(goal_id=goal_id, include_superseded=True)
        completed_step = next(step for step in completed if step["step_id"] == first_step_id)
        self.soft_assert_equal(completed_step["status"], "completed", "Completed step should be persisted")

        checkpoint_payload = await tool.function(
            ctx,
            operation="checkpoint",
            goal_id=goal_id,
            data={
                "step_id": second_step_id,
                "summary": "Reviewed sources and started open-question list.",
                "current_state": "Draft is not started yet.",
                "next_actions": ["Draft briefing", "Ask user about pricing stance"],
                "open_questions": ["Conservative or aggressive pricing recommendation?"],
                "risks": ["Security review owner remains unclear"],
            },
        )
        checkpoint = self._tool_payload(checkpoint_payload)["result"]
        self.soft_assert(checkpoint["checkpoint_id"].startswith("checkpoint_"), "Checkpoint id should be returned")
        self.soft_assert_equal(
            checkpoint["next_actions"],
            ["Draft briefing", "Ask user about pricing stance"],
            "Checkpoint should preserve next actions structurally",
        )

        latest_payload = await tool.function(ctx, operation="get_goal", goal_id=goal_id)
        latest_goal = self._tool_payload(latest_payload)["result"]
        self.soft_assert_equal(
            latest_goal["latest_checkpoint"]["checkpoint_id"],
            checkpoint["checkpoint_id"],
            "get_goal should include the latest checkpoint",
        )

        events_payload = await tool.function(ctx, operation="list_events", goal_id=goal_id)
        events = self._tool_payload(events_payload)["result"]
        event_types = [event["event_type"] for event in events]
        self.soft_assert(
            {"created", "plan_changed", "status_changed", "checkpoint"}.issubset(set(event_types)),
            "Goal events should capture creation, plan changes, status updates, and checkpoints",
        )

        list_payload = await tool.function(
            ctx,
            operation="list_goals",
            status="active",
            workspace_path_hint="Clients/Acme",
        )
        listed = self._tool_payload(list_payload)["result"]
        self.soft_assert_equal([item["goal_id"] for item in listed], [goal_id], "list_goals should filter by workspace hint")

        self.soft_assert(not self._table_exists("goal_artifacts"), "goal_ops should not create an artifact table")
        migration_status = get_system_migration_status(self._get_system_controller()._system_root)
        goal_target = next(target for target in migration_status.targets if target.db_name == "goal_ops")
        self.soft_assert_equal(goal_target.pending_versions, (), "goal_ops migration should be applied at startup")

        self.teardown_scenario()
        self.assert_no_failures()

    def _tool_payload(self, raw) -> dict:
        if hasattr(raw, "return_value"):
            raw = raw.return_value
        payload = json.loads(raw)
        self.soft_assert_equal(payload.get("status"), "ok", "goal_ops tool call should succeed")
        return payload

    def _superseded_step_rows(self, goal_id: str) -> list[sqlite3.Row]:
        db_path = self._get_system_controller()._system_root / "goal_ops.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(
                """
                SELECT *
                FROM goal_steps
                WHERE goal_id = ?
                  AND status = 'superseded'
                """,
                (goal_id,),
            ).fetchall()
        finally:
            conn.close()

    def _table_exists(self, table_name: str) -> bool:
        db_path = self._get_system_controller()._system_root / "goal_ops.db"
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = ?
                LIMIT 1
                """,
                (table_name,),
            ).fetchone()
        finally:
            conn.close()
        return row is not None
