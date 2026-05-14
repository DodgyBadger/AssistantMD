"""Synthetic fixture harness for workstream memory experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from pydantic_ai.embeddings import EmbedInputType, EmbeddingModel, EmbeddingResult
from pydantic_ai.usage import RequestUsage

from core.chat.schema import DB_NAME as CHAT_DB_NAME
from core.chat.schema import ensure_chat_sessions_schema
from core.database import connect_sqlite_from_system_db
from core.memory.workstreams import (
    WorkstreamArtifact,
    WorkstreamField,
    WorkstreamStore,
    normalize_field_value,
)
from core.vector import VectorService


DEFAULT_VAULT_NAME = "MemoryExperimentVault"


@dataclass(frozen=True)
class MemoryExperimentFixture:
    """Summary of a populated memory experiment fixture."""

    data_root: Path
    system_root: Path
    vault_root: Path
    vault_name: str
    session_ids: tuple[str, ...]
    workstream_ids: tuple[str, ...]


class MemoryExperimentHarness:
    """Build isolated synthetic memory fixtures for Slice 1 experiments."""

    def __init__(
        self,
        *,
        data_root: Path,
        system_root: Path,
        vault_name: str = DEFAULT_VAULT_NAME,
    ):
        self.data_root = data_root
        self.system_root = system_root
        self.vault_name = vault_name
        self.vault_root = data_root / "vaults" / vault_name
        self.store = WorkstreamStore(system_root=str(system_root))

    def populate(self) -> MemoryExperimentFixture:
        """Populate synthetic vault files, chat sessions, and workstreams."""
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.system_root.mkdir(parents=True, exist_ok=True)
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self._write_vault_files()
        ensure_chat_sessions_schema(str(self.system_root))

        sessions = _scenario_sessions()
        for session in sessions:
            self._insert_chat_session(session)

        workstream_ids = tuple(self._create_seed_workstreams())
        return MemoryExperimentFixture(
            data_root=self.data_root,
            system_root=self.system_root,
            vault_root=self.vault_root,
            vault_name=self.vault_name,
            session_ids=tuple(session["session_id"] for session in sessions),
            workstream_ids=workstream_ids,
        )

    def extraction_report(self, fixture: MemoryExperimentFixture) -> dict[str, Any]:
        """Return deterministic extraction output for all fixture sessions."""
        sessions: dict[str, Any] = {}
        for session_id in fixture.session_ids:
            fields = self.store.extract_candidate_fields_from_session(
                vault_name=fixture.vault_name,
                session_id=session_id,
            )
            sessions[session_id] = [field.to_dict() for field in fields]
        return {"vault_name": fixture.vault_name, "sessions": sessions}

    def related_report(self, fixture: MemoryExperimentFixture) -> dict[str, Any]:
        """Return explainable related candidates for all fixture workstreams."""
        workstreams: dict[str, Any] = {}
        for workstream_id in fixture.workstream_ids:
            candidates = self.store.related_workstream_candidates(
                vault_name=fixture.vault_name,
                workstream_id=workstream_id,
            )
            workstreams[workstream_id] = [candidate.to_dict() for candidate in candidates]
        return {"vault_name": fixture.vault_name, "workstreams": workstreams}

    async def semantic_report(
        self,
        fixture: MemoryExperimentFixture,
        *,
        vector_service: VectorService,
    ) -> dict[str, Any]:
        """Return vector-backed field-match candidates for selected query sessions."""
        for workstream_id in fixture.workstream_ids:
            await self.store.vectorize_workstream_fields(
                workstream_id=workstream_id,
                vector_service=vector_service,
            )

        queries: dict[str, Any] = {}
        for session_id in ("riparian-grant-session",):
            fields = self.store.extract_candidate_fields_from_session(
                vault_name=fixture.vault_name,
                session_id=session_id,
            )
            exact_topic_values = {
                field.normalized_value for field in fields if field.field_type == "topic"
            }
            exact_matches = []
            for value in exact_topic_values:
                exact_matches.extend(
                    workstream.to_dict()
                    for workstream in self.store.search_workstreams(
                        vault_name=fixture.vault_name,
                        field_type="topic",
                        normalized_value=value,
                    )
                )
            semantic_matches = await self.store.semantic_related_workstream_candidates(
                vault_name=fixture.vault_name,
                query_fields=tuple(field for field in fields if field.field_type == "topic"),
                vector_service=vector_service,
                min_score=0.78,
            )
            queries[session_id] = {
                "query_fields": [field.to_dict() for field in fields],
                "exact_topic_match_workstream_ids": [
                    workstream["workstream_id"] for workstream in exact_matches
                ],
                "semantic_candidates": [
                    candidate.to_dict() for candidate in semantic_matches
                ],
            }
        return {"vault_name": fixture.vault_name, "queries": queries}

    def _write_vault_files(self) -> None:
        files = {
            "Reports/Donor/Wetlands/report-draft.md": "# Wetlands Donor Report\n",
            "Reports/Donor/Forest/report-draft.md": "# Forest Donor Report\n",
            "Proposals/Wetlands/funding-proposal.md": "# Wetlands Funding Proposal\n",
            "Planning/Annual Goals.md": "# Annual Goals\n",
            "Planning/Weekly Plans/2026-W01.md": "# Weekly Plan\n",
            "Reviews/Performance Review 2026.md": "# Performance Review\n",
            "Research/Snippets/wetlands-clipping.md": "# Wetlands Clipping\n",
        }
        for relative_path, content in files.items():
            path = self.vault_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _insert_chat_session(self, session: dict[str, Any]) -> None:
        conn = connect_sqlite_from_system_db(CHAT_DB_NAME, str(self.system_root))
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO chat_sessions (
                    session_id, vault_name, title, metadata_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    self.vault_name,
                    session["title"],
                    json.dumps(session.get("metadata", {}), sort_keys=True),
                ),
            )
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id = ? AND vault_name = ?
                """,
                (session["session_id"], self.vault_name),
            )
            for index, message in enumerate(session["messages"]):
                conn.execute(
                    """
                    INSERT INTO chat_messages (
                        session_id, vault_name, sequence_index, direction,
                        message_type, role, content_text, message_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session["session_id"],
                        self.vault_name,
                        index,
                        message["direction"],
                        "model_message",
                        message["role"],
                        message["content"],
                        json.dumps(
                            {
                                "role": message["role"],
                                "content": message["content"],
                            },
                            sort_keys=True,
                        ),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _create_seed_workstreams(self) -> list[str]:
        seed_workstreams = _scenario_workstreams(self.vault_name)
        workstream_ids: list[str] = []
        for seed in seed_workstreams:
            workstream = self.store.create_workstream(
                workstream_id=seed["workstream_id"],
                vault_name=self.vault_name,
                title=seed["title"],
                weight=seed["weight"],
                confidence=seed["confidence"],
                metadata=seed.get("metadata", {}),
            )
            self.store.update_workstream_fields(
                workstream_id=workstream.workstream_id,
                fields=tuple(
                    WorkstreamField(
                        field_type=field["field_type"],
                        value=field["value"],
                        normalized_value=normalize_field_value(field["value"]),
                        confidence=field["confidence"],
                        source=field["source"],
                    )
                    for field in seed["fields"]
                ),
            )
            self.store.add_workstream_artifacts(
                workstream_id=workstream.workstream_id,
                artifacts=tuple(
                    WorkstreamArtifact(
                        vault_name=self.vault_name,
                        path=artifact["path"],
                        artifact_role=artifact["artifact_role"],
                        source=artifact["source"],
                        metadata=artifact.get("metadata", {}),
                    )
                    for artifact in seed["artifacts"]
                ),
            )
            session_id = seed.get("session_id")
            if session_id:
                self.store.link_session_to_workstream(
                    workstream_id=workstream.workstream_id,
                    vault_name=self.vault_name,
                    session_id=session_id,
                    link_source="seed_fixture",
                    confidence=0.95,
                )
            workstream_ids.append(workstream.workstream_id)
        return workstream_ids


def _scenario_sessions() -> list[dict[str, Any]]:
    return [
        {
            "session_id": "donor-wetlands-session",
            "title": "Wetlands donor report",
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": "Draft a donor report for North Star Foundation about wetlands.",
                },
                {
                    "direction": "response",
                    "role": "assistant",
                    "content": "I will reuse the donor report format and source notes.",
                },
            ],
        },
        {
            "session_id": "donor-forest-session",
            "title": "Forest donor report",
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": "Prepare a donor report for North Star Foundation about forests.",
                },
            ],
        },
        {
            "session_id": "wetlands-proposal-session",
            "title": "Wetlands funding proposal",
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": "Build a funding proposal about wetlands for River Fund.",
                },
            ],
        },
        {
            "session_id": "annual-review-session",
            "title": "Annual goals and performance review",
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": "Use annual goals and weekly plans to draft my performance review.",
                },
            ],
        },
        {
            "session_id": "retrieval-session",
            "title": "Find note about board decision",
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": "Where did I mention the board decision about topic X?",
                },
            ],
        },
        {
            "session_id": "snippets-session",
            "title": "Wetlands clipping synthesis",
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": "Synthesize the snippets in the wetlands research folder.",
                },
            ],
        },
        {
            "session_id": "riparian-grant-session",
            "title": "Riparian restoration grant application",
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": (
                        "Draft a grant proposal about riparian restoration and "
                        "watershed protection."
                    ),
                },
            ],
        },
        {
            "session_id": "incognito-session",
            "title": "Incognito quick check",
            "metadata": {"memory_mode": "off"},
            "messages": [
                {
                    "direction": "request",
                    "role": "user",
                    "content": "Do not remember this session. Quick check on one source file.",
                },
            ],
        },
    ]


def _scenario_workstreams(vault_name: str) -> list[dict[str, Any]]:
    del vault_name
    return [
        {
            "workstream_id": "workstream-donor-wetlands",
            "session_id": "donor-wetlands-session",
            "title": "Wetlands donor report",
            "weight": 7.5,
            "confidence": 0.9,
            "fields": [
                _field("type", "donor report", 0.95),
                _field("topic", "wetlands", 0.9),
                _field("organization", "North Star Foundation", 0.95),
                _field("strategy", "reuse format", 0.7),
            ],
            "artifacts": [
                _artifact("Reports/Donor/Wetlands/report-draft.md", "output_created"),
                _artifact("Research/Snippets/wetlands-clipping.md", "file_retrieved"),
            ],
        },
        {
            "workstream_id": "workstream-donor-forest",
            "session_id": "donor-forest-session",
            "title": "Forest donor report",
            "weight": 5.5,
            "confidence": 0.82,
            "fields": [
                _field("type", "donor report", 0.92),
                _field("topic", "forests", 0.86),
                _field("organization", "North Star Foundation", 0.94),
                _field("strategy", "reuse format", 0.65),
            ],
            "artifacts": [
                _artifact("Reports/Donor/Forest/report-draft.md", "output_created"),
            ],
        },
        {
            "workstream_id": "workstream-wetlands-proposal",
            "session_id": "wetlands-proposal-session",
            "title": "Wetlands funding proposal",
            "weight": 6.0,
            "confidence": 0.86,
            "fields": [
                _field("type", "funding proposal", 0.92),
                _field("topic", "wetlands", 0.93),
                _field("organization", "River Fund", 0.88),
            ],
            "artifacts": [
                _artifact("Proposals/Wetlands/funding-proposal.md", "output_created"),
                _artifact("Research/Snippets/wetlands-clipping.md", "file_retrieved"),
            ],
        },
        {
            "workstream_id": "workstream-annual-review",
            "session_id": "annual-review-session",
            "title": "Annual goals and performance review",
            "weight": 8.0,
            "confidence": 0.9,
            "fields": [
                _field("type", "performance review", 0.9),
                _field("topic", "annual goals", 0.9),
            ],
            "artifacts": [
                _artifact("Planning/Annual Goals.md", "file_retrieved"),
                _artifact("Planning/Weekly Plans/2026-W01.md", "file_retrieved"),
                _artifact("Reviews/Performance Review 2026.md", "output_created"),
            ],
        },
        {
            "workstream_id": "workstream-snippets-wetlands",
            "session_id": "snippets-session",
            "title": "Wetlands snippet synthesis",
            "weight": 4.0,
            "confidence": 0.78,
            "fields": [
                _field("type", "snippet synthesis", 0.8),
                _field("topic", "wetlands", 0.88),
            ],
            "artifacts": [
                _artifact("Research/Snippets/wetlands-clipping.md", "file_retrieved"),
            ],
        },
    ]


def _field(field_type: str, value: str, confidence: float) -> dict[str, Any]:
    return {
        "field_type": field_type,
        "value": value,
        "confidence": confidence,
        "source": "seed_fixture",
    }


def _artifact(path: str, artifact_role: str) -> dict[str, Any]:
    return {
        "path": path,
        "artifact_role": artifact_role,
        "source": "seed_fixture",
    }


class SemanticProbeEmbeddingModel(EmbeddingModel):
    """Deterministic semantic embedding model for memory experiments."""

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
    elif "performance review" in lowered or "annual goals" in lowered:
        base = (0.04, 0.05, 0.88, 0.22)
    else:
        base = (0.01, 0.01, 0.01, 0.01)
    vector = list(base[:dimensions])
    if len(vector) < dimensions:
        vector.extend([0.0] * (dimensions - len(vector)))
    return vector
