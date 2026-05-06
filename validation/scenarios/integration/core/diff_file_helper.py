"""Integration scenario for the diff_file tool."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class DiffFileHelperScenario(BaseScenario):
    """Validate diff_file compares current content with latest retained snapshot."""

    async def test_scenario(self):
        vault = self.create_vault("DiffFileHelperVault")
        self.create_file(vault, "notes/meeting_notes.md", "## Meeting Notes\n\n- Original item\n")
        self.create_file(vault, "AssistantMD/Authoring/mutate_note.md", MUTATE_NOTE_WORKFLOW)
        self.create_file(vault, "AssistantMD/Authoring/diff_note.md", DIFF_NOTE_WORKFLOW)
        self.create_file(vault, "AssistantMD/Authoring/diff_unavailable.md", DIFF_UNAVAILABLE_WORKFLOW)

        await self.start_system()

        mutate_result = await self.run_workflow(vault, "mutate_note")
        self.soft_assert_equal(mutate_result.status, "completed", "Mutation workflow should complete")

        checkpoint = self.event_checkpoint()
        diff_result = await self.run_workflow(vault, "diff_note")
        events = self.events_since(checkpoint)
        self.soft_assert_equal(diff_result.status, "completed", "Diff workflow should complete")
        self.assert_event_contains(
            events,
            name="authoring_direct_tool_completed",
            expected={
                "workflow_id": f"{vault.name}/diff_note",
                "tool": "diff_file",
                "status": "completed",
            },
        )
        self.assert_event_contains(
            events,
            name="diff_file_completed",
            expected={
                "path": "notes/meeting_notes.md",
                "available": True,
                "has_changes": True,
            },
        )
        diff_text = (Path(vault) / "notes/diff-output.md").read_text(encoding="utf-8")
        self.soft_assert("## Meeting Notes" in diff_text, "Diff should include unchanged context")
        self.soft_assert("+- Added item" in diff_text, "Diff should include added current line")

        checkpoint = self.event_checkpoint()
        unavailable_result = await self.run_workflow(vault, "diff_unavailable")
        unavailable_events = self.events_since(checkpoint)
        self.soft_assert_equal(
            unavailable_result.status,
            "completed",
            "Unavailable diff workflow should finish with handled unavailable status",
        )
        self.assert_event_contains(
            unavailable_events,
            name="authoring_direct_tool_completed",
            expected={
                "workflow_id": f"{vault.name}/diff_unavailable",
                "tool": "diff_file",
                "status": "unavailable",
            },
        )
        self.assert_event_contains(
            unavailable_events,
            name="diff_file_completed",
            expected={
                "path": "notes/no-snapshot.md",
                "available": False,
                "reason": "previous_snapshot_unavailable",
            },
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()


MUTATE_NOTE_WORKFLOW = """---
run_type: workflow
enabled: false
description: Mutate a note so diff_file has a retained previous snapshot
---

## Run

```python
await file_ops_safe(
    operation="append",
    path="notes/meeting_notes.md",
    content="- Added item\\n",
)
await finish(status="completed", reason="mutation-complete")
```
"""


DIFF_NOTE_WORKFLOW = """---
run_type: workflow
enabled: false
description: Diff current meeting notes against latest retained snapshot
---

## Run

```python
diff = await diff_file(path="notes/meeting_notes.md")
if not diff.metadata.get("available"):
    raise RuntimeError(diff.return_value)
if not diff.metadata.get("has_changes"):
    raise RuntimeError("Expected meeting notes diff to have changes")
await file_ops_safe(
    operation="write",
    path="notes/diff-output.md",
    content=diff.return_value,
)
await finish(status="completed", reason="diff-complete")
```
"""


DIFF_UNAVAILABLE_WORKFLOW = """---
run_type: workflow
enabled: false
description: Verify diff_file unavailable status
---

## Run

```python
diff = await diff_file(path="notes/no-snapshot.md")
if diff.metadata.get("available"):
    raise RuntimeError("Expected no-snapshot diff to be unavailable")
if diff.metadata.get("reason") != "previous_snapshot_unavailable":
    raise RuntimeError(f"Unexpected unavailable reason: {diff.metadata.get('reason')}")
await finish(status="completed", reason="diff-unavailable-ok")
```
"""
