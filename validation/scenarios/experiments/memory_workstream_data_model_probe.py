"""
Experiment scenario for the Slice 1 workstream memory data model.

This scenario intentionally validates deterministic artifacts from synthetic
fixtures before default chat behavior is wired into memory.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.memory.experiment_harness import MemoryExperimentHarness, SemanticProbeEmbeddingModel
from core.vector import VectorService
from validation.core.base_scenario import BaseScenario


class MemoryWorkstreamDataModelProbeScenario(BaseScenario):
    """Probe workstream extraction and related-query shape."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        data_root = Path(controller.test_data_root)
        system_root = controller._system_root

        harness = MemoryExperimentHarness(
            data_root=data_root,
            system_root=system_root,
        )
        fixture = harness.populate()
        extraction = harness.extraction_report(fixture)
        related = harness.related_report(fixture)
        semantic = await harness.semantic_report(
            fixture,
            vector_service=VectorService(
                embedding_model_overrides={
                    "embeddings": SemanticProbeEmbeddingModel(dimensions=1536)
                }
            ),
        )

        report = {
            "fixture": {
                "vault_name": fixture.vault_name,
                "session_ids": fixture.session_ids,
                "workstream_ids": fixture.workstream_ids,
            },
            "extraction": extraction,
            "related": related,
            "semantic": semantic,
        }
        (self.artifacts_dir / "memory_workstream_data_model_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        sessions = extraction["sessions"]
        self.soft_assert(
            _has_field(sessions["donor-wetlands-session"], "type", "donor report"),
            "Donor wetlands session should extract donor report type",
        )
        self.soft_assert(
            _has_field(sessions["donor-wetlands-session"], "topic", "wetlands"),
            "Donor wetlands session should extract wetlands topic",
        )
        self.soft_assert(
            _has_field(
                sessions["donor-wetlands-session"],
                "organization",
                "north star foundation",
            ),
            "Donor wetlands session should extract North Star Foundation",
        )
        self.soft_assert(
            _has_field(sessions["wetlands-proposal-session"], "type", "funding proposal"),
            "Wetlands proposal session should extract funding proposal type",
        )
        self.soft_assert(
            _has_field(sessions["retrieval-session"], "type", "retrieval"),
            "Pure retrieval session should extract retrieval type",
        )
        self.soft_assert_equal(
            sessions["incognito-session"],
            [],
            "Incognito fixture should not produce candidate fields",
        )

        riparian_fields = sessions["riparian-grant-session"]
        self.soft_assert(
            _has_field(riparian_fields, "topic", "riparian restoration"),
            "Riparian grant session should extract riparian restoration topic",
        )
        self.soft_assert(
            _has_field(riparian_fields, "topic", "watershed protection"),
            "Riparian grant session should extract watershed protection topic",
        )

        donor_candidates = related["workstreams"]["workstream-donor-wetlands"]
        donor_forest = _candidate(donor_candidates, "workstream-donor-forest")
        wetlands_proposal = _candidate(donor_candidates, "workstream-wetlands-proposal")
        self.soft_assert(
            donor_forest is not None and "same_type" in donor_forest["relation_types"],
            "Forest donor report should relate by same task type",
        )
        self.soft_assert(
            wetlands_proposal is not None
            and "same_topic" in wetlands_proposal["relation_types"],
            "Wetlands proposal should relate by same topic",
        )

        semantic_query = semantic["queries"]["riparian-grant-session"]
        self.soft_assert_equal(
            semantic_query["exact_topic_match_workstream_ids"],
            [],
            "Riparian query should not have exact topic matches in seeded workstreams",
        )
        semantic_ids = [
            candidate["workstream_id"]
            for candidate in semantic_query["semantic_candidates"]
        ]
        self.soft_assert(
            "workstream-wetlands-proposal" in semantic_ids,
            "Riparian query should retrieve wetlands proposal through semantic field vectors",
        )
        self.soft_assert(
            "workstream-donor-wetlands" in semantic_ids,
            "Riparian query should retrieve wetlands donor report through semantic field vectors",
        )

        self.teardown_scenario()
        self.assert_no_failures()


def _has_field(fields: list[dict], field_type: str, normalized_value: str) -> bool:
    return any(
        field["field_type"] == field_type and field["normalized_value"] == normalized_value
        for field in fields
    )


def _candidate(candidates: list[dict], workstream_id: str) -> dict | None:
    for candidate in candidates:
        if candidate["workstream_id"] == workstream_id:
            return candidate
    return None
