"""
Experiment scenario for session memory field storage and semantic search.
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai.embeddings import EmbedInputType, EmbeddingModel, EmbeddingResult
from pydantic_ai.usage import RequestUsage

from core.memory.session_memory import (
    SessionMemoryArtifact,
    SessionMemoryStore,
)
from core.vector import VectorService
from validation.core.base_scenario import BaseScenario


class MemorySessionDataModelProbeScenario(BaseScenario):
    """Probe the core session memory model and field-aware semantic retrieval."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        _seed_legacy_memory_db(controller._system_root)
        store = SessionMemoryStore(system_root=str(controller._system_root))
        vault_name = "MemoryModelProbeVault"

        migrated_memory = store.get_session_memory(
            vault_name=vault_name,
            session_id="legacy-session",
        )
        self.soft_assert(migrated_memory is not None, "Legacy memory row should survive schema migration")
        self.soft_assert(
            migrated_memory is not None and migrated_memory.source_summary is None,
            "Legacy memory row should have empty source_summary after migration",
        )
        store.upsert_session_memory(
            session_id="legacy-session",
            vault_name=vault_name,
            source_summary="Read legacy source notes before migration.",
        )
        migrated_source_matches = store.search_session_memories_fts(
            vault_name=vault_name,
            query="legacy source notes",
        )
        self.soft_assert(
            any(result.session_memory.session_id == "legacy-session" for result in migrated_source_matches),
            "Migrated FTS table should index source_summary after update",
        )

        session_ids = _seed_session_memories(store, vault_name)
        vector_service = VectorService(
            embedding_model_overrides={
                "embeddings": SemanticProbeEmbeddingModel(dimensions=1536)
            }
        )
        for session_id in session_ids:
            await store.index_session_memory_fields(
                vault_name=vault_name,
                session_id=session_id,
                vector_service=vector_service,
            )

        substring_riparian = store.search_session_memories(
            vault_name=vault_name,
            field_type="user_intent",
            value="riparian restoration",
        )
        semantic_riparian = await store.search_session_memories_by_field(
            vault_name=vault_name,
            field_type="user_intent",
            value="riparian restoration",
            vector_service=vector_service,
            min_score=0.78,
        )
        substring_donor = store.search_session_memories(
            vault_name=vault_name,
            field_type="work_product",
            value="donor report",
        )
        related_sessions = await store.find_related_sessions(
            vault_name=vault_name,
            session_id="session-riparian-proposal",
            vector_service=vector_service,
            limit=5,
        )

        report = {
            "vault_name": vault_name,
            "session_ids": session_ids,
            "migrated_source_matches": [result.to_dict() for result in migrated_source_matches],
            "substring_riparian": [memory.to_dict() for memory in substring_riparian],
            "semantic_riparian": [result.to_dict() for result in semantic_riparian],
            "substring_donor": [memory.to_dict() for memory in substring_donor],
            "related_sessions": [result.to_dict() for result in related_sessions],
        }
        (self.artifacts_dir / "memory_session_data_model_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.soft_assert_equal(
            len(substring_riparian),
            1,
            "Riparian query should find substring user-intent matches in seeded sessions",
        )
        self.soft_assert(
            any(memory.session_id == "session-riparian-proposal" for memory in substring_riparian),
            "Substring search should retrieve the directly matching riparian proposal",
        )
        semantic_ids = [
            result.session_memory.session_id for result in semantic_riparian
        ]
        self.soft_assert(
            "session-wetlands-proposal" in semantic_ids,
            "Riparian query should retrieve wetlands proposal through semantic field vectors",
        )
        self.soft_assert(
            "session-donor-wetlands" in semantic_ids,
            "Riparian query should retrieve wetlands donor report through semantic field vectors",
        )
        self.soft_assert(
            "session-donor-forest" not in semantic_ids,
            "Field-aware semantic search should not pull unrelated forest topics",
        )
        self.soft_assert(
            all(result.match_type in {"substring", "semantic"} for result in semantic_riparian),
            "Search results should expose how each session memory matched",
        )
        self.soft_assert(
            any(memory.session_id == "session-donor-wetlands" for memory in substring_donor),
            "Substring field search should still retrieve direct field matches",
        )
        related_ids = [
            result.session_memory.session_id for result in related_sessions
        ]
        self.soft_assert(
            "session-wetlands-proposal" in related_ids,
            "Related-session retrieval should find adjacent proposal work",
        )
        self.soft_assert(
            all(result.session_memory.session_id != "session-riparian-proposal"
                for result in related_sessions),
            "Related-session retrieval should exclude the query session",
        )
        self.soft_assert(
            all(result.contributions for result in related_sessions),
            "Related-session results should include field contribution evidence",
        )

        self.teardown_scenario()
        self.assert_no_failures()


def _seed_legacy_memory_db(system_root: Path) -> None:
    """Create a pre-source_summary memory DB before SessionMemoryStore migrates it."""
    system_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(system_root / "memory.db")
    try:
        conn.executescript(
            """
            CREATE TABLE session_memories (
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                domain TEXT,
                work_product TEXT,
                user_intent TEXT,
                named_entities TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                PRIMARY KEY (session_id, vault_name)
            );
            CREATE VIRTUAL TABLE session_memories_fts USING fts5(
                session_id UNINDEXED,
                vault_name UNINDEXED,
                title,
                summary,
                domain,
                work_product,
                user_intent,
                named_entities,
                tokenize = 'unicode61'
            );
            INSERT INTO session_memories (
                session_id, vault_name, title, summary, domain,
                work_product, user_intent, named_entities, metadata_json
            ) VALUES (
                'legacy-session',
                'MemoryModelProbeVault',
                'Legacy memory',
                'Existing memory row before source summary.',
                'validation',
                'migration probe',
                'Validate memory schema migration.',
                '',
                '{}'
            );
            INSERT INTO session_memories_fts (
                session_id, vault_name, title, summary, domain,
                work_product, user_intent, named_entities
            ) VALUES (
                'legacy-session',
                'MemoryModelProbeVault',
                'Legacy memory',
                'Existing memory row before source summary.',
                'validation',
                'migration probe',
                'Validate memory schema migration.',
                ''
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _seed_session_memories(store: SessionMemoryStore, vault_name: str) -> tuple[str, ...]:
    seeds = [
        {
            "session_id": "session-donor-wetlands",
            "title": "Wetlands donor report",
            "fields": [
                "Prepared a donor report about wetlands restoration work.",
                "conservation fundraising",
                "donor report",
                "Create a donor report about wetlands restoration.",
                "North Star Foundation",
            ],
            "artifacts": [
                ("Reports/Donor/Wetlands/report-draft.md", "output_created"),
            ],
        },
        {
            "session_id": "session-donor-forest",
            "title": "Forest donor report",
            "fields": [
                "Prepared a donor report about forest conservation work.",
                "conservation fundraising",
                "donor report",
                "Create a donor report about forest conservation.",
                "North Star Foundation",
            ],
            "artifacts": [
                ("Reports/Donor/Forest/report-draft.md", "output_created"),
            ],
        },
        {
            "session_id": "session-wetlands-proposal",
            "title": "Wetlands funding proposal",
            "fields": [
                "Prepared a funding proposal about wetlands restoration work.",
                "conservation fundraising",
                "funding proposal",
                "Create a funding proposal for wetlands restoration.",
                "River Fund",
            ],
            "artifacts": [
                ("Proposals/Wetlands/funding-proposal.md", "output_created"),
            ],
        },
        {
            "session_id": "session-riparian-proposal",
            "title": "Riparian funding proposal",
            "fields": [
                "Prepared a funding proposal about riparian restoration work.",
                "conservation fundraising",
                "funding proposal",
                "Create a funding proposal for riparian restoration.",
                "River Fund",
            ],
            "artifacts": [
                ("Proposals/Riparian/funding-proposal.md", "output_created"),
            ],
        },
    ]
    session_ids: list[str] = []
    for seed in seeds:
        session_memory = store.upsert_session_memory(
            session_id=seed["session_id"],
            vault_name=vault_name,
            title=seed["title"],
            summary=seed["fields"][0],
            domain=seed["fields"][1],
            work_product=seed["fields"][2],
            user_intent=seed["fields"][3],
            named_entities=seed["fields"][4],
        )
        store.add_session_artifacts(
            vault_name=vault_name,
            session_id=session_memory.session_id,
            artifacts=tuple(
                SessionMemoryArtifact(
                    vault_name=vault_name,
                    path=path,
                    artifact_role=artifact_role,
                )
                for path, artifact_role in seed["artifacts"]
            ),
        )
        session_ids.append(session_memory.session_id)
    return tuple(session_ids)


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
