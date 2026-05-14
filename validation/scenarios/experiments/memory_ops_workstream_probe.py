"""
Experiment scenario for the refactored memory_ops workstream contract.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.memory.experiment_harness import MemoryExperimentHarness
from core.tools.memory_ops import MemoryOps
from validation.core.base_scenario import BaseScenario


class MemoryOpsWorkstreamProbeScenario(BaseScenario):
    """Probe memory_ops workstream operations without chat tool registration."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        data_root = Path(controller.test_data_root)
        system_root = controller._system_root

        harness = MemoryExperimentHarness(
            data_root=data_root,
            system_root=system_root,
        )
        fixture = harness.populate()

        tool = MemoryOps.get_tool()
        ctx = SimpleNamespace(
            deps=SimpleNamespace(
                session_id="riparian-grant-session",
                vault_name=fixture.vault_name,
                message_history=(),
            )
        )

        created = await _call(
            tool,
            ctx,
            operation="create_workstream",
            title="Riparian restoration grant",
            fields=[
                {"field_type": "type", "value": "funding proposal", "confidence": 0.8},
                {"field_type": "topic", "value": "riparian restoration", "confidence": 0.8},
            ],
            artifacts=[
                {
                    "path": "Proposals/Riparian/grant.md",
                    "artifact_role": "planning_note",
                }
            ],
            confidence=0.7,
        )
        created_id = created["workstream"]["workstream_id"]

        linked = await _call(
            tool,
            ctx,
            operation="link_session",
            workstream_id=created_id,
            confidence=0.9,
        )
        current = await _call(tool, ctx, operation="current_workstream")
        updated = await _call(
            tool,
            ctx,
            operation="update_workstream",
            workstream_id=created_id,
            field_type="strategy",
            value="reuse grant narrative",
            confidence=0.6,
        )
        searched = await _call(
            tool,
            ctx,
            operation="search_workstreams",
            field_type="topic",
            value="riparian restoration",
        )
        artifacts = await _call(
            tool,
            ctx,
            operation="workstream_artifacts",
            workstream_id=created_id,
        )
        related = await _call(
            tool,
            ctx,
            operation="related_workstreams",
            workstream_id="workstream-donor-wetlands",
            limit=3,
        )
        unlinked = await _call(tool, ctx, operation="unlink_session")
        current_after_unlink = await _call(tool, ctx, operation="current_workstream")

        report = {
            "created": created,
            "linked": linked,
            "current": current,
            "updated": updated,
            "searched": searched,
            "artifacts": artifacts,
            "related": related,
            "unlinked": unlinked,
            "current_after_unlink": current_after_unlink,
        }
        (self.artifacts_dir / "memory_ops_workstream_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.soft_assert_equal(created["status"], "ok", "create_workstream should succeed")
        self.soft_assert_equal(linked["workstream"]["workstream_id"], created_id)
        self.soft_assert_equal(current["status"], "linked")
        self.soft_assert(
            any(
                field["field_type"] == "strategy"
                and field["normalized_value"] == "reuse grant narrative"
                for field in updated["workstream"]["fields"]
            ),
            "update_workstream should add strategy field",
        )
        self.soft_assert(
            any(workstream["workstream_id"] == created_id for workstream in searched["workstreams"]),
            "search_workstreams should find created topic",
        )
        self.soft_assert_equal(len(artifacts["artifacts"]), 1)
        self.soft_assert(
            any(candidate["workstream_id"] == "workstream-wetlands-proposal" for candidate in related["candidates"]),
            "related_workstreams should return exact related candidates",
        )
        self.soft_assert_equal(unlinked["status"], "ok")
        self.soft_assert_equal(current_after_unlink["status"], "unlinked")

        self.teardown_scenario()
        self.assert_no_failures()


async def _call(tool, ctx, **kwargs) -> dict:
    raw = await tool.function(ctx, **kwargs)
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed
