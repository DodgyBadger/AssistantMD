# goal_ops

Track durable goals, ordered steps, events, and checkpoints for longer work.

`goal_ops` records state only. It does not execute work, write files, schedule
workflows, or automatically retry tool calls.

Common operations:

- `create_goal`: create a goal, optionally with initial steps.
- `list_goals`: list goals in the active vault.
- `get_goal`: fetch a goal with its active steps and latest checkpoint.
- `update_goal`: update title, objective, status, workspace hint, success criteria, or metadata.
- `replace_steps`: replace the active step plan in one transaction.
- `update_steps`: update multiple existing steps in one transaction.
- `list_steps`: list ordered steps.
- `add_events`: add one or more audit events.
- `list_events`: list goal audit events.
- `checkpoint`: record a compact recovery checkpoint.
- `get_latest_checkpoint`: fetch the latest checkpoint.

Parameters:

- `operation`: required operation name.
- `goal_id`: required for goal-specific operations.
- `status`: optional `list_goals` status filter.
- `query`: optional `list_goals` title/objective search.
- `limit`: optional result limit.
- `include_superseded`: include superseded steps where supported.
- `workspace_path_hint`: optional non-authoritative workspace hint filter.
- `data`: operation-specific object payload.

Create a goal with initial steps:

```json
{
  "operation": "create_goal",
  "data": {
    "title": "Prepare Acme renewal briefing",
    "objective": "Create a renewal briefing from project notes and recent meetings.",
    "workspace_path_hint": "Clients/Acme",
    "success_criteria": [
      "Draft briefing exists",
      "Open questions are listed",
      "Source notes are cited"
    ],
    "steps": [
      {"title": "Review source notes"},
      {"title": "Extract renewal risks"},
      {"title": "Draft briefing"}
    ]
  }
}
```

Rework a plan in one call:

```json
{
  "operation": "replace_steps",
  "goal_id": "goal_abc",
  "data": {
    "reason": "User asked to simplify the plan.",
    "steps": [
      {"title": "Review notes", "position": 10},
      {"title": "Draft briefing", "position": 20},
      {"title": "List open questions", "position": 30}
    ]
  }
}
```

Update several steps:

```json
{
  "operation": "update_steps",
  "goal_id": "goal_abc",
  "data": {
    "reason": "Finished source review and started drafting.",
    "updates": [
      {"step_id": "step_1", "status": "completed"},
      {"step_id": "step_2", "status": "in_progress", "summary": "Drafting risk table."}
    ]
  }
}
```

Record a checkpoint:

```json
{
  "operation": "checkpoint",
  "goal_id": "goal_abc",
  "data": {
    "step_id": "step_2",
    "summary": "Reviewed May and June notes. Main renewal risks are pricing and security review ownership.",
    "current_state": "Draft briefing is started.",
    "next_actions": ["Pull source quotes", "Finish risk table"],
    "open_questions": ["Should pricing recommendation be conservative or aggressive?"],
    "risks": ["Security owner is unclear"]
  }
}
```

Step ordering uses explicit numeric `position`, not ids or titles. If positions
are omitted in batch operations, `goal_ops` assigns sparse positions from array
order: `10`, `20`, `30`, and so on.
