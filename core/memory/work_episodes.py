"""Work episode memory persistence and deterministic experiment helpers."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.chat.schema import DB_NAME as CHAT_DB_NAME
from core.chat.schema import ensure_chat_sessions_schema
from core.database import connect_sqlite_from_system_db
from core.memory.schema import DB_NAME, ensure_memory_schema
from core.vector import SQLitePythonVectorStore, VectorService, VectorStore


FIELD_TYPES = {
    "type",
    "topic",
    "person",
    "organization",
    "project",
    "objective",
    "strategy",
}
VECTOR_FIELD_TYPES = {"type", "topic", "objective", "strategy"}
FIELD_VECTOR_NAMESPACE = "work_episode_fields"
FIELD_VECTOR_TABLE = "work_episode_field_vectors"


@dataclass(frozen=True)
class WorkEpisodeField:
    """One typed query dimension for a work episode."""

    field_type: str
    value: str
    normalized_value: str
    confidence: float
    source: str
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class WorkEpisodeArtifact:
    """One vault artifact associated with a work episode."""

    path: str
    artifact_role: str
    source: str
    vault_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class WorkEpisode:
    """Stored work episode with fields and artifacts."""

    episode_id: str
    vault_name: str
    title: str | None
    status: str
    weight: float
    confidence: float
    created_at: str
    last_seen_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    fields: tuple[WorkEpisodeField, ...] = ()
    artifacts: tuple[WorkEpisodeArtifact, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "episode_id": self.episode_id,
            "vault_name": self.vault_name,
            "title": self.title,
            "status": self.status,
            "weight": self.weight,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "metadata": self.metadata,
            "fields": [field.to_dict() for field in self.fields],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class RelatedEpisodeCandidate:
    """Explainable related episode candidate."""

    episode_id: str
    title: str | None
    relation_types: tuple[str, ...]
    reasons: tuple[str, ...]
    score: float

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class CandidateField:
    """Deterministically extracted candidate field from chat/session text."""

    field_type: str
    value: str
    normalized_value: str
    confidence: float
    source: str
    reason: str

    def to_episode_field(self) -> WorkEpisodeField:
        """Convert to the storage field shape."""
        return WorkEpisodeField(
            field_type=self.field_type,
            value=self.value,
            normalized_value=self.normalized_value,
            confidence=self.confidence,
            source=self.source,
        )

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


class WorkEpisodeStore:
    """SQLite-backed store for work episode memory."""

    def __init__(self, system_root: str | None = None):
        self.system_root = system_root
        ensure_memory_schema(system_root)

    def create_episode(
        self,
        *,
        vault_name: str,
        title: str | None = None,
        episode_id: str | None = None,
        status: str = "active",
        weight: float = 0,
        confidence: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> WorkEpisode:
        """Create and return a work episode without linking any session."""
        episode_id = episode_id or f"episode-{uuid4().hex}"
        now = _utc_now()
        metadata_json = _dump_json(metadata or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_episodes (
                    episode_id, vault_name, title, status, weight, confidence,
                    created_at, last_seen_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    vault_name,
                    title,
                    status,
                    weight,
                    confidence,
                    now,
                    now,
                    metadata_json,
                ),
            )
        episode = self.get_episode(episode_id)
        if episode is None:
            raise RuntimeError(f"Failed to create work episode {episode_id}")
        return episode

    def get_episode(self, episode_id: str) -> WorkEpisode | None:
        """Return one episode by id, including fields and artifacts."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT episode_id, vault_name, title, status, weight, confidence,
                       created_at, last_seen_at, metadata_json
                FROM work_episodes
                WHERE episode_id = ?
                """,
                (episode_id,),
            ).fetchone()
            if row is None:
                return None
            return self._episode_from_row(conn, row)

    def get_current_episode(
        self,
        *,
        vault_name: str,
        session_id: str,
    ) -> WorkEpisode | None:
        """Return the episode currently linked to a session, if any."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT e.episode_id, e.vault_name, e.title, e.status, e.weight,
                       e.confidence, e.created_at, e.last_seen_at, e.metadata_json
                FROM work_episode_sessions s
                JOIN work_episodes e ON e.episode_id = s.episode_id
                WHERE s.session_id = ? AND s.vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            if row is None:
                return None
            return self._episode_from_row(conn, row)

    def link_session_to_episode(
        self,
        *,
        episode_id: str,
        vault_name: str,
        session_id: str,
        link_source: str,
        confidence: float,
    ) -> WorkEpisode:
        """Link a session to one current episode in the same vault."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT vault_name FROM work_episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown work episode: {episode_id}")
            episode_vault = str(row["vault_name"])
            if episode_vault != vault_name:
                raise ValueError("Cannot link a session to an episode in another vault")
            conn.execute(
                """
                INSERT INTO work_episode_sessions (
                    episode_id, session_id, vault_name, linked_at, link_source, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, vault_name)
                DO UPDATE SET
                    episode_id = excluded.episode_id,
                    linked_at = excluded.linked_at,
                    link_source = excluded.link_source,
                    confidence = excluded.confidence
                """,
                (episode_id, session_id, vault_name, _utc_now(), link_source, confidence),
            )
            conn.execute(
                """
                UPDATE work_episodes
                SET last_seen_at = ?
                WHERE episode_id = ?
                """,
                (_utc_now(), episode_id),
            )
        episode = self.get_episode(episode_id)
        if episode is None:
            raise RuntimeError(f"Linked episode disappeared: {episode_id}")
        return episode

    def unlink_session_from_episode(self, *, vault_name: str, session_id: str) -> None:
        """Remove the current episode link for a session."""
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM work_episode_sessions
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )

    def update_episode_fields(
        self,
        *,
        episode_id: str,
        fields: list[WorkEpisodeField] | tuple[WorkEpisodeField, ...],
    ) -> None:
        """Upsert typed fields for an episode."""
        with self._connect() as conn:
            if not self._episode_exists(conn, episode_id):
                raise ValueError(f"Unknown work episode: {episode_id}")
            now = _utc_now()
            for field_value in fields:
                _validate_field_type(field_value.field_type)
                conn.execute(
                    """
                    INSERT INTO work_episode_fields (
                        episode_id, field_type, value, normalized_value, confidence,
                        source, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(episode_id, field_type, normalized_value, source)
                    DO UPDATE SET
                        value = excluded.value,
                        confidence = MAX(work_episode_fields.confidence, excluded.confidence),
                        updated_at = excluded.updated_at
                    """,
                    (
                        episode_id,
                        field_value.field_type,
                        field_value.value,
                        field_value.normalized_value,
                        field_value.confidence,
                        field_value.source,
                        now,
                        now,
                    ),
                )

    def add_episode_artifacts(
        self,
        *,
        episode_id: str,
        artifacts: list[WorkEpisodeArtifact] | tuple[WorkEpisodeArtifact, ...],
    ) -> None:
        """Upsert vault artifacts for an episode."""
        with self._connect() as conn:
            if not self._episode_exists(conn, episode_id):
                raise ValueError(f"Unknown work episode: {episode_id}")
            now = _utc_now()
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO work_episode_artifacts (
                        episode_id, vault_name, path, artifact_role, source,
                        created_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(episode_id, path, artifact_role, source)
                    DO UPDATE SET
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        episode_id,
                        artifact.vault_name,
                        artifact.path,
                        artifact.artifact_role,
                        artifact.source,
                        now,
                        _dump_json(artifact.metadata),
                    ),
                )

    def list_episode_artifacts(self, episode_id: str) -> tuple[WorkEpisodeArtifact, ...]:
        """List artifacts for one episode."""
        with self._connect() as conn:
            return self._artifacts_for_episode(conn, episode_id)

    def record_feedback(
        self,
        *,
        current_episode_id: str,
        related_episode_id: str,
        action: str,
        reason: str | None = None,
    ) -> None:
        """Record user/system feedback on an episode relationship."""
        with self._connect() as conn:
            if not self._episode_exists(conn, current_episode_id):
                raise ValueError(f"Unknown current work episode: {current_episode_id}")
            if not self._episode_exists(conn, related_episode_id):
                raise ValueError(f"Unknown related work episode: {related_episode_id}")
            conn.execute(
                """
                INSERT INTO work_episode_feedback (
                    current_episode_id, related_episode_id, action, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    current_episode_id,
                    related_episode_id,
                    action,
                    reason,
                    _utc_now(),
                ),
            )

    def search_episodes(
        self,
        *,
        vault_name: str,
        field_type: str | None = None,
        normalized_value: str | None = None,
        limit: int = 20,
    ) -> tuple[WorkEpisode, ...]:
        """Search episodes by vault and optionally a normalized field."""
        with self._connect() as conn:
            if field_type and normalized_value:
                rows = conn.execute(
                    """
                    SELECT DISTINCT e.episode_id, e.vault_name, e.title, e.status,
                           e.weight, e.confidence, e.created_at, e.last_seen_at,
                           e.metadata_json
                    FROM work_episodes e
                    JOIN work_episode_fields f ON f.episode_id = e.episode_id
                    WHERE e.vault_name = ?
                      AND f.field_type = ?
                      AND f.normalized_value = ?
                    ORDER BY e.weight DESC, e.last_seen_at DESC
                    LIMIT ?
                    """,
                    (vault_name, field_type, normalized_value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT episode_id, vault_name, title, status, weight, confidence,
                           created_at, last_seen_at, metadata_json
                    FROM work_episodes
                    WHERE vault_name = ?
                    ORDER BY weight DESC, last_seen_at DESC
                    LIMIT ?
                    """,
                    (vault_name, limit),
                ).fetchall()
            return tuple(self._episode_from_row(conn, row) for row in rows)

    def related_episode_candidates(
        self,
        *,
        vault_name: str,
        episode_id: str,
        limit: int = 10,
    ) -> tuple[RelatedEpisodeCandidate, ...]:
        """Return explainable related episode candidates for experiments."""
        episode = self.get_episode(episode_id)
        if episode is None:
            raise ValueError(f"Unknown work episode: {episode_id}")
        if episode.vault_name != vault_name:
            raise ValueError("Cannot search related episodes across vaults")

        candidate_reasons: dict[str, list[str]] = {}
        candidate_relations: dict[str, set[str]] = {}
        candidate_scores: dict[str, float] = {}

        field_weights = {
            "organization": 4.0,
            "person": 4.0,
            "project": 3.5,
            "type": 2.5,
            "topic": 2.0,
            "objective": 1.25,
            "strategy": 1.0,
        }
        for field_value in episode.fields:
            matches = self.search_episodes(
                vault_name=vault_name,
                field_type=field_value.field_type,
                normalized_value=field_value.normalized_value,
                limit=50,
            )
            for match in matches:
                if match.episode_id == episode_id:
                    continue
                relation = f"same_{field_value.field_type}"
                reason = f"{field_value.field_type}: {field_value.value}"
                weight = field_weights.get(field_value.field_type, 1.0)
                score = weight + field_value.confidence + match.confidence
                candidate_reasons.setdefault(match.episode_id, []).append(reason)
                candidate_relations.setdefault(match.episode_id, set()).add(relation)
                candidate_scores[match.episode_id] = (
                    candidate_scores.get(match.episode_id, 0) + score
                )

        for artifact in episode.artifacts:
            folder = artifact.path.rsplit("/", 1)[0] if "/" in artifact.path else ""
            for match in self._episodes_with_artifact_context(vault_name, artifact.path, folder):
                if match.episode_id == episode_id:
                    continue
                if artifact.path in {item.path for item in match.artifacts}:
                    relation = "same_artifact_path"
                    reason = f"artifact path: {artifact.path}"
                    score = 2.5
                else:
                    relation = "same_folder_namespace"
                    reason = f"folder: {folder}"
                    score = 1.0
                candidate_reasons.setdefault(match.episode_id, []).append(reason)
                candidate_relations.setdefault(match.episode_id, set()).add(relation)
                candidate_scores[match.episode_id] = (
                    candidate_scores.get(match.episode_id, 0) + score
                )

        candidates: list[RelatedEpisodeCandidate] = []
        for candidate_id, score in candidate_scores.items():
            candidate = self.get_episode(candidate_id)
            if candidate is None:
                continue
            candidates.append(
                RelatedEpisodeCandidate(
                    episode_id=candidate.episode_id,
                    title=candidate.title,
                    relation_types=tuple(sorted(candidate_relations[candidate_id])),
                    reasons=tuple(dict.fromkeys(candidate_reasons[candidate_id])),
                    score=round(score + candidate.weight, 3),
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        return tuple(candidates[:limit])

    async def vectorize_episode_fields(
        self,
        *,
        episode_id: str,
        vector_service: VectorService,
        vector_store: VectorStore | None = None,
        model_alias: str = "embeddings",
    ) -> int:
        """Embed vector-searchable fields for one episode."""
        episode = self.get_episode(episode_id)
        if episode is None:
            raise ValueError(f"Unknown work episode: {episode_id}")
        fields = tuple(
            field_value
            for field_value in episode.fields
            if field_value.id is not None and field_value.field_type in VECTOR_FIELD_TYPES
        )
        if not fields:
            return 0

        store = vector_store or self._field_vector_store()
        inputs = [_field_embedding_text(field_value) for field_value in fields]
        embedding_result = await vector_service.embed_documents(inputs, model_alias=model_alias)
        for field_value, embedding in zip(fields, embedding_result.vectors, strict=True):
            store.upsert(
                namespace=FIELD_VECTOR_NAMESPACE,
                item_id=str(field_value.id),
                embedding=embedding,
                metadata={
                    "episode_id": episode.episode_id,
                    "vault_name": episode.vault_name,
                    "field_type": field_value.field_type,
                    "field_value": field_value.value,
                    "normalized_value": field_value.normalized_value,
                    "source": field_value.source,
                    "confidence": field_value.confidence,
                },
            )
        return len(fields)

    async def semantic_related_episode_candidates(
        self,
        *,
        vault_name: str,
        query_fields: tuple[CandidateField | WorkEpisodeField, ...],
        vector_service: VectorService,
        vector_store: VectorStore | None = None,
        model_alias: str = "embeddings",
        limit: int = 10,
        min_score: float = 0.78,
    ) -> tuple[RelatedEpisodeCandidate, ...]:
        """Return vector-backed related episode candidates from extracted fields."""
        fields = tuple(
            field_value
            for field_value in query_fields
            if field_value.field_type in VECTOR_FIELD_TYPES
        )
        if not fields:
            return ()

        store = vector_store or self._field_vector_store()
        candidate_reasons: dict[str, list[str]] = {}
        candidate_relations: dict[str, set[str]] = {}
        candidate_scores: dict[str, float] = {}

        for field_value in fields:
            input_text = _field_embedding_text(field_value)
            query_embedding = await vector_service.embed_query(
                input_text,
                model_alias=model_alias,
            )
            hits = store.search_similar(
                namespace=FIELD_VECTOR_NAMESPACE,
                query=query_embedding.vectors[0],
                limit=limit * 4,
                min_score=min_score,
            )
            for hit in hits:
                metadata = hit.metadata
                if metadata.get("vault_name") != vault_name:
                    continue
                episode_id = str(metadata.get("episode_id") or "")
                if not episode_id:
                    continue
                matched_type = str(metadata.get("field_type") or "")
                matched_value = str(metadata.get("field_value") or hit.text)
                relation = f"semantic_{matched_type or field_value.field_type}_similarity"
                reason = (
                    f"{relation}: {field_value.value} ~= {matched_value} "
                    f"({hit.score:.2f})"
                )
                confidence = float(metadata.get("confidence") or 0)
                candidate_reasons.setdefault(episode_id, []).append(reason)
                candidate_relations.setdefault(episode_id, set()).add(relation)
                candidate_scores[episode_id] = (
                    candidate_scores.get(episode_id, 0) + hit.score + confidence
                )

        candidates: list[RelatedEpisodeCandidate] = []
        for episode_id, score in candidate_scores.items():
            episode = self.get_episode(episode_id)
            if episode is None:
                continue
            candidates.append(
                RelatedEpisodeCandidate(
                    episode_id=episode.episode_id,
                    title=episode.title,
                    relation_types=tuple(sorted(candidate_relations[episode_id])),
                    reasons=tuple(dict.fromkeys(candidate_reasons[episode_id])),
                    score=round(score + episode.weight, 3),
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        return tuple(candidates[:limit])

    def extract_candidate_fields_from_session(
        self,
        *,
        vault_name: str,
        session_id: str,
    ) -> tuple[CandidateField, ...]:
        """Extract deterministic candidate fields from a stored chat session."""
        ensure_chat_sessions_schema(self.system_root)
        conn = connect_sqlite_from_system_db(CHAT_DB_NAME, self.system_root)
        conn.row_factory = sqlite3.Row
        try:
            session = conn.execute(
                """
                SELECT title
                FROM chat_sessions
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            if session is None:
                raise ValueError(f"Unknown chat session: {session_id}")
            rows = conn.execute(
                """
                SELECT content_text
                FROM chat_messages
                WHERE session_id = ? AND vault_name = ?
                ORDER BY sequence_index ASC
                """,
                (session_id, vault_name),
            ).fetchall()
        finally:
            conn.close()

        text_parts = [str(session["title"] or "")]
        text_parts.extend(str(row["content_text"] or "") for row in rows)
        return extract_candidate_fields("\n".join(text_parts))

    def _connect(self) -> sqlite3.Connection:
        ensure_memory_schema(self.system_root)
        conn = connect_sqlite_from_system_db(DB_NAME, self.system_root)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _field_vector_store(self) -> SQLitePythonVectorStore:
        return SQLitePythonVectorStore(
            db_name=DB_NAME,
            table_name=FIELD_VECTOR_TABLE,
            system_root=self.system_root,
        )

    def _episode_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> WorkEpisode:
        episode_id = str(row["episode_id"])
        return WorkEpisode(
            episode_id=episode_id,
            vault_name=str(row["vault_name"]),
            title=str(row["title"]) if row["title"] is not None else None,
            status=str(row["status"]),
            weight=float(row["weight"] or 0),
            confidence=float(row["confidence"] or 0),
            created_at=str(row["created_at"]),
            last_seen_at=str(row["last_seen_at"]),
            metadata=_load_json(row["metadata_json"]),
            fields=self._fields_for_episode(conn, episode_id),
            artifacts=self._artifacts_for_episode(conn, episode_id),
        )

    def _fields_for_episode(
        self,
        conn: sqlite3.Connection,
        episode_id: str,
    ) -> tuple[WorkEpisodeField, ...]:
        rows = conn.execute(
            """
            SELECT id, field_type, value, normalized_value, confidence, source
            FROM work_episode_fields
            WHERE episode_id = ?
            ORDER BY field_type ASC, normalized_value ASC
            """,
            (episode_id,),
        ).fetchall()
        return tuple(
            WorkEpisodeField(
                id=int(row["id"]),
                field_type=str(row["field_type"]),
                value=str(row["value"]),
                normalized_value=str(row["normalized_value"]),
                confidence=float(row["confidence"] or 0),
                source=str(row["source"]),
            )
            for row in rows
        )

    def _artifacts_for_episode(
        self,
        conn: sqlite3.Connection,
        episode_id: str,
    ) -> tuple[WorkEpisodeArtifact, ...]:
        rows = conn.execute(
            """
            SELECT vault_name, path, artifact_role, source, metadata_json
            FROM work_episode_artifacts
            WHERE episode_id = ?
            ORDER BY path ASC, artifact_role ASC
            """,
            (episode_id,),
        ).fetchall()
        return tuple(
            WorkEpisodeArtifact(
                vault_name=str(row["vault_name"]),
                path=str(row["path"]),
                artifact_role=str(row["artifact_role"]),
                source=str(row["source"]),
                metadata=_load_json(row["metadata_json"]),
            )
            for row in rows
        )

    def _episode_exists(self, conn: sqlite3.Connection, episode_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM work_episodes WHERE episode_id = ? LIMIT 1",
            (episode_id,),
        ).fetchone()
        return row is not None

    def _episodes_with_artifact_context(
        self,
        vault_name: str,
        path: str,
        folder: str,
    ) -> tuple[WorkEpisode, ...]:
        with self._connect() as conn:
            like_pattern = f"{folder}/%" if folder else "%"
            rows = conn.execute(
                """
                SELECT DISTINCT e.episode_id, e.vault_name, e.title, e.status,
                       e.weight, e.confidence, e.created_at, e.last_seen_at,
                       e.metadata_json
                FROM work_episodes e
                JOIN work_episode_artifacts a ON a.episode_id = e.episode_id
                WHERE e.vault_name = ?
                  AND (a.path = ? OR a.path LIKE ?)
                """,
                (vault_name, path, like_pattern),
            ).fetchall()
            return tuple(self._episode_from_row(conn, row) for row in rows)


def extract_candidate_fields(text: str) -> tuple[CandidateField, ...]:
    """Extract deterministic candidate fields for Slice 1 experiments."""
    normalized_text = text.lower()
    candidates: list[CandidateField] = []

    rules = [
        (r"\bdonor report\b|\bclient report\b", "type", "donor report", 0.78),
        (r"\bfunding proposal\b|\bgrant proposal\b", "type", "funding proposal", 0.78),
        (r"\bperformance review\b", "type", "performance review", 0.78),
        (r"\bweekly plan\b|\bweekly task", "type", "weekly planning", 0.7),
        (r"\bsnippet\b|\bresearch folder\b|\bclipping", "type", "snippet synthesis", 0.68),
        (r"\bwhere did i mention\b|\bfind my note\b|\bpure retrieval\b", "type", "retrieval", 0.66),
        (r"\bwetlands?\b", "topic", "wetlands", 0.8),
        (r"\briparian\b", "topic", "riparian restoration", 0.72),
        (r"\bwatershed protection\b|\bwatershed\b", "topic", "watershed protection", 0.72),
        (r"\bannual goals?\b", "topic", "annual goals", 0.76),
        (r"\bperformance review\b", "topic", "performance review", 0.72),
        (r"\bformat\b|\btemplate\b|\bstyle\b", "strategy", "reuse format", 0.58),
    ]
    for pattern, field_type, value, confidence in rules:
        if re.search(pattern, normalized_text):
            candidates.append(
                _candidate(
                    field_type=field_type,
                    value=value,
                    confidence=confidence,
                    reason=f"matched pattern: {pattern}",
                )
            )

    for organization in _extract_organizations(text):
        candidates.append(
            _candidate(
                field_type="organization",
                value=organization,
                confidence=0.72,
                reason="matched organization-like phrase",
            )
        )

    objective = _first_sentence_with_verb(text)
    if objective:
        candidates.append(
            _candidate(
                field_type="objective",
                value=objective,
                confidence=0.52,
                reason="first short action-oriented sentence",
            )
        )

    deduped: dict[tuple[str, str], CandidateField] = {}
    for candidate in candidates:
        key = (candidate.field_type, candidate.normalized_value)
        existing = deduped.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            deduped[key] = candidate
    return tuple(deduped.values())


def _candidate(
    *,
    field_type: str,
    value: str,
    confidence: float,
    reason: str,
) -> CandidateField:
    _validate_field_type(field_type)
    return CandidateField(
        field_type=field_type,
        value=value,
        normalized_value=normalize_field_value(value),
        confidence=confidence,
        source="deterministic_experiment",
        reason=reason,
    )


def normalize_field_value(value: str) -> str:
    """Normalize a field value for exact lookup experiments."""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _field_embedding_text(field_value: CandidateField | WorkEpisodeField) -> str:
    return f"{field_value.field_type}: {field_value.value}"


def _extract_organizations(text: str) -> tuple[str, ...]:
    organizations: list[str] = []
    patterns = [
        r"\b([A-Z][A-Za-z0-9&]+(?:\s+[A-Z][A-Za-z0-9&]+){0,4}\sFoundation)\b",
        r"\b([A-Z][A-Za-z0-9&]+(?:\s+[A-Z][A-Za-z0-9&]+){0,4}\sFund)\b",
        r"\b([A-Z][A-Za-z0-9&]+(?:\s+[A-Z][A-Za-z0-9&]+){0,4}\sClient)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = re.sub(r"\s+", " ", match.group(1)).strip()
            if value and value not in organizations:
                organizations.append(value)
    return tuple(organizations)


def _first_sentence_with_verb(text: str) -> str | None:
    for raw_sentence in re.split(r"[\n.!?]+", text):
        sentence = re.sub(r"\s+", " ", raw_sentence).strip()
        if not sentence or len(sentence) > 140:
            continue
        lowered = sentence.lower()
        if any(verb in lowered for verb in ("write", "draft", "find", "build", "prepare")):
            return sentence
    return None


def _validate_field_type(field_type: str) -> None:
    if field_type not in FIELD_TYPES:
        available = ", ".join(sorted(FIELD_TYPES))
        raise ValueError(f"Unsupported work episode field type '{field_type}'. Use: {available}")


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
