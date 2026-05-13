"""
Experiment scenario for the refactored memory_ops work episode contract.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.memory.experiment_harness import MemoryExperimentHarness
from core.tools.memory_ops import MemoryOps
from validation.core.base_scenario import BaseScenario


class MemoryOpsEpisodeProbeScenario(BaseScenario):
    """Probe memory_ops work episode operations without chat tool registration."""

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
            operation="create_episode",
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
        created_id = created["episode"]["episode_id"]

        linked = await _call(
            tool,
            ctx,
            operation="link_session",
            episode_id=created_id,
            confidence=0.9,
        )
        current = await _call(tool, ctx, operation="current_episode")
        updated = await _call(
            tool,
            ctx,
            operation="update_episode",
            episode_id=created_id,
            field_type="strategy",
            value="reuse grant narrative",
            confidence=0.6,
        )
        searched = await _call(
            tool,
            ctx,
            operation="search_episodes",
            field_type="topic",
            value="riparian restoration",
        )
        artifacts = await _call(
            tool,
            ctx,
            operation="episode_artifacts",
            episode_id=created_id,
        )
        related = await _call(
            tool,
            ctx,
            operation="related_episodes",
            episode_id="episode-donor-wetlands",
            limit=3,
        )
        unlinked = await _call(tool, ctx, operation="unlink_session")
        current_after_unlink = await _call(tool, ctx, operation="current_episode")

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
        (self.artifacts_dir / "memory_ops_episode_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.soft_assert_equal(created["status"], "ok", "create_episode should succeed")
        self.soft_assert_equal(linked["episode"]["episode_id"], created_id)
        self.soft_assert_equal(current["status"], "linked")
        self.soft_assert(
            any(
                field["field_type"] == "strategy"
                and field["normalized_value"] == "reuse grant narrative"
                for field in updated["episode"]["fields"]
            ),
            "update_episode should add strategy field",
        )
        self.soft_assert(
            any(episode["episode_id"] == created_id for episode in searched["episodes"]),
            "search_episodes should find created topic",
        )
        self.soft_assert_equal(len(artifacts["artifacts"]), 1)
        self.soft_assert(
            any(candidate["episode_id"] == "episode-wetlands-proposal" for candidate in related["candidates"]),
            "related_episodes should return exact related candidates",
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
