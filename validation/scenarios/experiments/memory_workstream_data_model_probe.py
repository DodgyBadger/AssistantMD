"""
Experiment scenario for workstream field storage and semantic search.
"""

import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai.embeddings import EmbedInputType, EmbeddingModel, EmbeddingResult
from pydantic_ai.usage import RequestUsage

from core.memory.workstreams import (
    WorkstreamArtifact,
    WorkstreamStore,
)
from core.vector import VectorService
from validation.core.base_scenario import BaseScenario


class MemoryWorkstreamDataModelProbeScenario(BaseScenario):
    """Probe the core workstream model and field-aware semantic retrieval."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        store = WorkstreamStore(system_root=str(controller._system_root))
        vault_name = "MemoryModelProbeVault"

        workstream_ids = _seed_workstreams(store, vault_name)
        vector_service = VectorService(
            embedding_model_overrides={
                "embeddings": SemanticProbeEmbeddingModel(dimensions=1536)
            }
        )
        for workstream_id in workstream_ids:
            await store.index_workstream_fields(
                workstream_id=workstream_id,
                vector_service=vector_service,
            )

        exact_riparian = store.search_workstreams(
            vault_name=vault_name,
            field_type="topic",
            value="riparian restoration",
        )
        semantic_riparian = await store.search_workstreams_by_field(
            vault_name=vault_name,
            field_type="topic",
            value="riparian restoration",
            vector_service=vector_service,
            min_score=0.78,
        )
        exact_donor = store.search_workstreams(
            vault_name=vault_name,
            field_type="type",
            value="donor report",
        )

        report = {
            "vault_name": vault_name,
            "workstream_ids": workstream_ids,
            "exact_riparian": [workstream.to_dict() for workstream in exact_riparian],
            "semantic_riparian": [result.to_dict() for result in semantic_riparian],
            "exact_donor": [workstream.to_dict() for workstream in exact_donor],
        }
        (self.artifacts_dir / "memory_workstream_data_model_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.soft_assert_equal(
            len(exact_riparian),
            0,
            "Riparian query should not have exact topic matches in seeded workstreams",
        )
        semantic_ids = [
            result.workstream.workstream_id for result in semantic_riparian
        ]
        self.soft_assert(
            "workstream-wetlands-proposal" in semantic_ids,
            "Riparian query should retrieve wetlands proposal through semantic field vectors",
        )
        self.soft_assert(
            "workstream-donor-wetlands" in semantic_ids,
            "Riparian query should retrieve wetlands donor report through semantic field vectors",
        )
        self.soft_assert(
            "workstream-donor-forest" not in semantic_ids,
            "Field-aware semantic search should not pull unrelated forest topics",
        )
        self.soft_assert(
            all(result.match_type in {"exact", "semantic"} for result in semantic_riparian),
            "Search results should expose how each workstream matched",
        )
        self.soft_assert(
            any(workstream.workstream_id == "workstream-donor-wetlands" for workstream in exact_donor),
            "Exact field search should still retrieve by normalized field value",
        )

        self.teardown_scenario()
        self.assert_no_failures()


def _seed_workstreams(store: WorkstreamStore, vault_name: str) -> tuple[str, ...]:
    seeds = [
        {
            "workstream_id": "workstream-donor-wetlands",
            "title": "Wetlands donor report",
            "fields": [
                "donor report",
                "wetlands",
                "North Star Foundation",
            ],
            "artifacts": [
                ("Reports/Donor/Wetlands/report-draft.md", "output_created"),
            ],
        },
        {
            "workstream_id": "workstream-donor-forest",
            "title": "Forest donor report",
            "fields": [
                "donor report",
                "forests",
                "North Star Foundation",
            ],
            "artifacts": [
                ("Reports/Donor/Forest/report-draft.md", "output_created"),
            ],
        },
        {
            "workstream_id": "workstream-wetlands-proposal",
            "title": "Wetlands funding proposal",
            "fields": [
                "funding proposal",
                "wetlands",
                "River Fund",
            ],
            "artifacts": [
                ("Proposals/Wetlands/funding-proposal.md", "output_created"),
            ],
        },
    ]
    workstream_ids: list[str] = []
    for seed in seeds:
        workstream = store.create_workstream(
            workstream_id=seed["workstream_id"],
            vault_name=vault_name,
            title=seed["title"],
            type=seed["fields"][0],
            topic=seed["fields"][1],
            entities=seed["fields"][2],
        )
        store.add_workstream_artifacts(
            workstream_id=workstream.workstream_id,
            artifacts=tuple(
                WorkstreamArtifact(
                    vault_name=vault_name,
                    path=path,
                    artifact_role=artifact_role,
                )
                for path, artifact_role in seed["artifacts"]
            ),
        )
        workstream_ids.append(workstream.workstream_id)
    return tuple(workstream_ids)


class SemanticProbeEmbeddingModel(EmbeddingModel):
    """Deterministic semantic embedding model for memory validation."""

    def __init__(self, *, dimensions: int = 1536):
        self._dimensions = dimensions
        super().__init__()

    @property
    def model_name(self) -> str:
        return "semantic-probe"

    @property
    def system(self) -> str:
        return "test"

    async def embed(
        self,
        inputs: str | Sequence[str],
        *,
        input_type: EmbedInputType,
        settings: dict[str, Any] | None = None,
    ) -> EmbeddingResult:
        input_list, merged_settings = self.prepare_embed(inputs, settings)
        dimensions = int(merged_settings.get("dimensions") or self._dimensions)
        return EmbeddingResult(
            embeddings=[_semantic_probe_vector(text, dimensions) for text in input_list],
            inputs=input_list,
            input_type=input_type,
            model_name=self.model_name,
            provider_name=self.system,
            usage=RequestUsage(input_tokens=sum(len(text.split()) for text in input_list)),
        )


def _semantic_probe_vector(text: str, dimensions: int) -> list[float]:
    lowered = text.lower()
    if "wetland" in lowered:
        base = (0.96, 0.18, 0.08, 0.0)
    elif "riparian" in lowered:
        base = (0.9, 0.28, 0.14, 0.0)
    elif "watershed" in lowered:
        base = (0.86, 0.34, 0.18, 0.0)
    elif "forest" in lowered:
        base = (0.18, 0.94, 0.08, 0.0)
    elif "donor report" in lowered:
        base = (0.1, 0.0, 0.18, 0.92)
    elif "funding proposal" in lowered or "grant proposal" in lowered:
        base = (0.16, 0.0, 0.12, 0.86)
    else:
        base = (0.01, 0.01, 0.01, 0.01)
    vector = list(base[:dimensions])
    if len(vector) < dimensions:
        vector.extend([0.0] * (dimensions - len(vector)))
    return vector
