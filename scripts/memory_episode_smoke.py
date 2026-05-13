"""Run Slice 1 work episode memory smoke experiments."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    """Create an isolated fixture and assert core experiment expectations."""
    with tempfile.TemporaryDirectory(prefix="assistantmd-memory-smoke-") as tmp:
        root = Path(tmp)
        from core.runtime.paths import set_bootstrap_roots

        set_bootstrap_roots(root / "data", root / "system")

        from core.memory.experiment_harness import (
            MemoryExperimentHarness,
            SemanticProbeEmbeddingModel,
        )
        from core.vector import VectorService

        harness = MemoryExperimentHarness(
            data_root=root / "data",
            system_root=root / "system",
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

        _assert_extraction(extraction)
        _assert_related(related)
        _assert_semantic(semantic)

        print(
            json.dumps(
                {
                    "fixture": {
                        "system_root": str(fixture.system_root),
                        "vault_name": fixture.vault_name,
                        "session_count": len(fixture.session_ids),
                        "episode_count": len(fixture.episode_ids),
                    },
                    "extraction": extraction,
                    "related": related,
                    "semantic": semantic,
                },
                indent=2,
                sort_keys=True,
            )
        )


def _assert_extraction(report: dict) -> None:
    sessions = report["sessions"]
    assert _has_field(sessions["donor-wetlands-session"], "type", "donor report")
    assert _has_field(sessions["donor-wetlands-session"], "topic", "wetlands")
    assert _has_field(
        sessions["donor-wetlands-session"],
        "organization",
        "north star foundation",
    )
    assert _has_field(sessions["wetlands-proposal-session"], "type", "funding proposal")
    assert _has_field(sessions["retrieval-session"], "type", "retrieval")
    assert _has_field(sessions["snippets-session"], "type", "snippet synthesis")


def _assert_related(report: dict) -> None:
    candidates = report["episodes"]["episode-donor-wetlands"]
    candidate_ids = [candidate["episode_id"] for candidate in candidates]
    assert "episode-donor-forest" in candidate_ids
    assert "episode-wetlands-proposal" in candidate_ids
    donor_forest = next(
        candidate for candidate in candidates if candidate["episode_id"] == "episode-donor-forest"
    )
    wetlands_proposal = next(
        candidate
        for candidate in candidates
        if candidate["episode_id"] == "episode-wetlands-proposal"
    )
    assert "same_type" in donor_forest["relation_types"]
    assert "same_topic" in wetlands_proposal["relation_types"]


def _assert_semantic(report: dict) -> None:
    query = report["queries"]["riparian-grant-session"]
    assert query["exact_topic_match_episode_ids"] == []
    candidate_ids = [
        candidate["episode_id"] for candidate in query["semantic_candidates"]
    ]
    assert "episode-wetlands-proposal" in candidate_ids
    assert "episode-donor-wetlands" in candidate_ids
    wetlands_proposal = next(
        candidate
        for candidate in query["semantic_candidates"]
        if candidate["episode_id"] == "episode-wetlands-proposal"
    )
    assert any(
        relation.startswith("semantic_topic") for relation in wetlands_proposal["relation_types"]
    )


def _has_field(fields: list[dict], field_type: str, normalized_value: str) -> bool:
    return any(
        field["field_type"] == field_type and field["normalized_value"] == normalized_value
        for field in fields
    )


if __name__ == "__main__":
    asyncio.run(main())
