"""Session summary persistence and field-aware retrieval."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.database import connect_sqlite_from_system_db
from core.memory.schema import DB_NAME, ensure_session_summary_schema
from core.vector import SQLitePythonVectorStore, VectorService, VectorStore


SESSION_SUMMARY_TEXT_FIELDS = (
    "summary",
    "domain",
    "work_product",
    "user_intent",
    "named_entities",
    "source_summary",
)
VECTOR_FIELD_TYPES = {"summary", "domain", "work_product", "user_intent"}
WILDCARD_FIELD_TYPES = {"named_entities"}
SUMMARY_VECTOR_MIN_SCORE = 0.50
FIELD_VECTOR_NAMESPACE = "session_summary_fields"
FIELD_VECTOR_TABLE = "session_summary_field_vectors"
RELATED_SESSION_FIELD_WEIGHTS = {
    "domain": 0.45,
    "work_product": 0.35,
    "user_intent": 0.20,
}
RELATED_SESSION_FIELD_MIN_SCORE = SUMMARY_VECTOR_MIN_SCORE
RELATED_SESSION_AUTOMATIC_THRESHOLD = 0.70
RELATED_SESSION_POSSIBLE_THRESHOLD = 0.55


class _UnsetValue:
    """Sentinel for omitted session summary fields."""


SESSION_SUMMARY_FIELD_UNSET = _UnsetValue()
SessionSummaryTextInput = str | None | _UnsetValue
SessionSummaryMetadataInput = dict[str, Any] | None | _UnsetValue


@dataclass(frozen=True)
class SessionSummaryArtifact:
    """One vault artifact associated with a chat session summary."""

    path: str
    artifact_role: str
    vault_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class SessionSummary:
    """Stored summary extracted from one chat session."""

    session_id: str
    vault_name: str
    title: str | None
    created_at: str
    updated_at: str
    summary: str | None = None
    domain: str | None = None
    work_product: str | None = None
    user_intent: str | None = None
    named_entities: str | None = None
    source_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[SessionSummaryArtifact, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "session_id": self.session_id,
            "vault_name": self.vault_name,
            "title": self.title,
            "summary": self.summary,
            "domain": self.domain,
            "work_product": self.work_product,
            "user_intent": self.user_intent,
            "named_entities": self.named_entities,
            "source_summary": self.source_summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    def field_value(self, field_type: str) -> str | None:
        """Return a queryable session summary field value by name."""
        _validate_field_type(field_type)
        value = getattr(self, field_type)
        return str(value) if value else None


@dataclass(frozen=True)
class SessionSummarySearchResult:
    """One field-aware session summary search result."""

    session_summary: SessionSummary
    match_type: str
    matched_fields: tuple[dict[str, Any], ...]
    score: float | None = None
    rank: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "session_summary": self.session_summary.to_dict(),
            "match_type": self.match_type,
            "matched_fields": list(self.matched_fields),
            "score": self.score,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class RelatedSessionContribution:
    """One field contribution to a related-session score."""

    field_type: str
    match_type: str
    score: float
    weight: float
    weighted_score: float
    query_value: str
    matched_value: str | None

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class RelatedSessionResult:
    """One compound related-session retrieval result."""

    session_summary: SessionSummary
    band: str
    score: float
    matched_field_count: int
    contributions: tuple[RelatedSessionContribution, ...]

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "session_summary": self.session_summary.to_dict(),
            "band": self.band,
            "score": self.score,
            "matched_field_count": self.matched_field_count,
            "contributions": [
                contribution.to_dict()
                for contribution in self.contributions
            ],
        }


class SessionSummaryStore:
    """SQLite-backed store for session summary."""

    def __init__(self, system_root: str | None = None):
        self.system_root = system_root
        ensure_session_summary_schema(system_root)

    def upsert_session_summary(
        self,
        *,
        vault_name: str,
        session_id: str,
        title: str | None = None,
        summary: SessionSummaryTextInput = SESSION_SUMMARY_FIELD_UNSET,
        domain: SessionSummaryTextInput = SESSION_SUMMARY_FIELD_UNSET,
        work_product: SessionSummaryTextInput = SESSION_SUMMARY_FIELD_UNSET,
        user_intent: SessionSummaryTextInput = SESSION_SUMMARY_FIELD_UNSET,
        named_entities: SessionSummaryTextInput = SESSION_SUMMARY_FIELD_UNSET,
        source_summary: SessionSummaryTextInput = SESSION_SUMMARY_FIELD_UNSET,
        metadata: SessionSummaryMetadataInput = SESSION_SUMMARY_FIELD_UNSET,
    ) -> SessionSummary:
        """Create or update summary fields for one chat session."""
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_summaries (
                    session_id, vault_name, title,
                    summary, domain, work_product, user_intent, named_entities,
                    source_summary,
                    created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, vault_name)
                DO UPDATE SET
                    title = COALESCE(excluded.title, session_summaries.title),
                    summary = CASE
                        WHEN ? THEN excluded.summary
                        ELSE session_summaries.summary
                    END,
                    domain = CASE
                        WHEN ? THEN excluded.domain
                        ELSE session_summaries.domain
                    END,
                    work_product = CASE
                        WHEN ? THEN excluded.work_product
                        ELSE session_summaries.work_product
                    END,
                    user_intent = CASE
                        WHEN ? THEN excluded.user_intent
                        ELSE session_summaries.user_intent
                    END,
                    named_entities = CASE
                        WHEN ? THEN excluded.named_entities
                        ELSE session_summaries.named_entities
                    END,
                    source_summary = CASE
                        WHEN ? THEN excluded.source_summary
                        ELSE session_summaries.source_summary
                    END,
                    updated_at = excluded.updated_at,
                    metadata_json = CASE
                        WHEN ? THEN excluded.metadata_json
                        ELSE session_summaries.metadata_json
                    END
                """,
                (
                    session_id,
                    vault_name,
                    _clean_text(title),
                    _clean_upsert_text(summary),
                    _clean_upsert_text(domain),
                    _clean_upsert_text(work_product),
                    _clean_upsert_text(user_intent),
                    _clean_upsert_text(named_entities),
                    _clean_upsert_text(source_summary),
                    now,
                    now,
                    _dump_upsert_metadata(metadata),
                    _is_upsert_value_supplied(summary),
                    _is_upsert_value_supplied(domain),
                    _is_upsert_value_supplied(work_product),
                    _is_upsert_value_supplied(user_intent),
                    _is_upsert_value_supplied(named_entities),
                    _is_upsert_value_supplied(source_summary),
                    _is_upsert_value_supplied(metadata),
                ),
            )
            row = conn.execute(
                f"""
                SELECT {self._session_summary_select_columns()}
                FROM session_summaries
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Failed to upsert session summary {session_id}")
            self._upsert_fts_row(conn, row)
        session_summary = self.get_session_summary(
            vault_name=vault_name,
            session_id=session_id,
        )
        if session_summary is None:
            raise RuntimeError(f"Failed to upsert session summary {session_id}")
        return session_summary

    def update_session_summary_fields(
        self,
        *,
        vault_name: str,
        session_id: str,
        summary: str | None = None,
        domain: str | None = None,
        work_product: str | None = None,
        user_intent: str | None = None,
        named_entities: str | None = None,
        source_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionSummary:
        """Replace editable summary fields for one existing session summary."""
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE session_summaries
                SET summary = ?,
                    domain = ?,
                    work_product = ?,
                    user_intent = ?,
                    named_entities = ?,
                    source_summary = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE session_id = ? AND vault_name = ?
                """,
                (
                    _clean_text(summary),
                    _clean_text(domain),
                    _clean_text(work_product),
                    _clean_text(user_intent),
                    _clean_text(named_entities),
                    _clean_text(source_summary),
                    _dump_json(metadata or {}),
                    now,
                    session_id,
                    vault_name,
                ),
            )
            if cursor.rowcount <= 0:
                raise ValueError(f"Unknown session summary: {session_id}")
            row = conn.execute(
                f"""
                SELECT {self._session_summary_select_columns()}
                FROM session_summaries
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Failed to update session summary {session_id}")
            self._upsert_fts_row(conn, row)

        session_summary = self.get_session_summary(
            vault_name=vault_name,
            session_id=session_id,
        )
        if session_summary is None:
            raise RuntimeError(f"Failed to update session summary {session_id}")
        return session_summary

    def get_session_summary(
        self,
        *,
        vault_name: str,
        session_id: str,
    ) -> SessionSummary | None:
        """Return one session summary by vault and session id."""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self._session_summary_select_columns()}
                FROM session_summaries
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            if row is None:
                return None
            return self._session_summary_from_row(conn, row)

    def delete_session_summary(self, *, vault_name: str, session_id: str) -> bool:
        """Delete one session summary row and associated artifacts."""
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM session_summaries_fts
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )
            cursor = conn.execute(
                """
                DELETE FROM session_summaries
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )
            deleted = cursor.rowcount > 0
        if deleted:
            self._delete_field_vectors(vault_name=vault_name, session_id=session_id)
        return deleted

    def search_session_summaries_fts(
        self,
        *,
        vault_name: str,
        query: str,
        limit: int = 20,
    ) -> tuple[SessionSummarySearchResult, ...]:
        """Search session summary fields with SQLite FTS5/BM25."""
        fts_query = build_fts_query(query)
        if not fts_query or limit <= 0:
            return ()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, bm25(
                    session_summaries_fts,
                    0.0, 0.0, 1.0, 0.8, 0.75, 0.95, 0.6, 0.5
                ) AS rank
                FROM session_summaries_fts
                WHERE vault_name = ?
                  AND session_summaries_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (vault_name, fts_query, limit),
            ).fetchall()
            results: list[SessionSummarySearchResult] = []
            for row in rows:
                session_id = str(row["session_id"])
                session_summary = self.get_session_summary(
                    vault_name=vault_name,
                    session_id=session_id,
                )
                if session_summary is None:
                    continue
                rank = float(row["rank"])
                coverage = _fts_query_coverage(query, session_summary)
                score = round(_bm25_score(rank) * max(coverage, 0.5), 6)
                if score <= 0.0:
                    continue
                results.append(
                    SessionSummarySearchResult(
                        session_summary=session_summary,
                        match_type="lexical",
                        matched_fields=(
                            {
                                "field_type": "session_summary",
                                "query_value": query,
                                "matched_value": None,
                                "match_type": "lexical",
                                "fts_query": fts_query,
                                "term_coverage": coverage,
                            },
                        ),
                        score=score,
                        rank=round(rank, 6),
                    )
                )
            return tuple(results)

    def add_session_artifacts(
        self,
        *,
        vault_name: str,
        session_id: str,
        artifacts: list[SessionSummaryArtifact] | tuple[SessionSummaryArtifact, ...],
    ) -> None:
        """Upsert vault artifacts for one session summary."""
        with self._connect() as conn:
            if not self._session_summary_exists(conn, vault_name=vault_name, session_id=session_id):
                raise ValueError(f"Unknown session summary: {session_id}")
            now = _utc_now()
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO session_summary_artifacts (
                        session_id, vault_name, path, artifact_role,
                        created_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, vault_name, path, artifact_role)
                    DO UPDATE SET
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        session_id,
                        vault_name,
                        artifact.path,
                        artifact.artifact_role,
                        now,
                        _dump_json(artifact.metadata),
                    ),
                )

    def search_session_summaries(
        self,
        *,
        vault_name: str,
        field_type: str | None = None,
        value: str | None = None,
        limit: int = 20,
    ) -> tuple[SessionSummary, ...]:
        """Search session summaries by vault and optionally one substring field value."""
        with self._connect() as conn:
            if field_type and value:
                _validate_field_type(field_type)
                where_clause = f"lower({field_type}) LIKE ? ESCAPE '\\'"
                field_value = f"%{_escape_like(value.lower().strip())}%"
                rows = conn.execute(
                    f"""
                    SELECT {self._session_summary_select_columns()}
                    FROM session_summaries
                    WHERE vault_name = ?
                      AND {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (vault_name, field_value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT {self._session_summary_select_columns()}
                    FROM session_summaries
                    WHERE vault_name = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (vault_name, limit),
                ).fetchall()
            return tuple(self._session_summary_from_row(conn, row) for row in rows)

    async def search_session_summaries_by_field(
        self,
        *,
        vault_name: str,
        field_type: str,
        value: str,
        vector_service: VectorService,
        vector_store: VectorStore | None = None,
        limit: int = 20,
        min_score: float = 0.0,
        model_alias: str = "embeddings",
        include_direct: bool = True,
    ) -> tuple[SessionSummarySearchResult, ...]:
        """Search one session summary field using optional substring plus vectors."""
        _validate_field_type(field_type)
        results: list[SessionSummarySearchResult] = []
        if include_direct:
            direct_matches = self.search_session_summaries(
                vault_name=vault_name,
                field_type=field_type,
                value=value,
                limit=limit,
            )
            results.extend(
                SessionSummarySearchResult(
                    session_summary=memory,
                    match_type=_direct_match_type(field_type),
                    matched_fields=(
                        {
                            "field_type": field_type,
                            "query_value": value,
                            "matched_value": memory.field_value(field_type),
                            "match_type": _direct_match_type(field_type),
                        },
                    ),
                    score=1.0,
                )
                for memory in direct_matches
            )

        if field_type not in VECTOR_FIELD_TYPES:
            return tuple(results)

        store = vector_store or self._field_vector_store()
        query = await vector_service.embed_query(
            _field_embedding_text(field_type=field_type, value=value),
            model_alias=model_alias,
        )
        hits = store.search_similar(
            namespace=FIELD_VECTOR_NAMESPACE,
            query=query.vectors[0],
            limit=limit * 4,
            min_score=min_score,
        )
        for hit in hits:
            metadata = hit.metadata
            if metadata.get("vault_name") != vault_name:
                continue
            if metadata.get("field_type") != field_type:
                continue
            session_id = str(metadata.get("session_id") or "")
            if not session_id:
                continue
            session_summary = self.get_session_summary(
                vault_name=vault_name,
                session_id=session_id,
            )
            if session_summary is None:
                continue
            current_value = session_summary.field_value(field_type)
            if not current_value:
                continue
            results.append(
                SessionSummarySearchResult(
                    session_summary=session_summary,
                    match_type="semantic",
                    matched_fields=(
                        {
                            "field_type": field_type,
                            "query_value": value,
                            "matched_value": current_value,
                            "match_type": "semantic",
                        },
                    ),
                    score=round(hit.score, 6),
                )
            )
        return tuple(results)

    async def find_related_sessions(
        self,
        *,
        vault_name: str,
        vector_service: VectorService,
        session_id: str | None = None,
        domain: str | None = None,
        work_product: str | None = None,
        user_intent: str | None = None,
        limit: int = 5,
        min_score: float = RELATED_SESSION_POSSIBLE_THRESHOLD,
        vector_store: VectorStore | None = None,
        model_alias: str = "embeddings",
    ) -> tuple[RelatedSessionResult, ...]:
        """Find related session summaries using the current compound policy."""
        if limit <= 0:
            return ()
        query_memory: SessionSummary | None = None
        if session_id:
            query_memory = self.get_session_summary(
                vault_name=vault_name,
                session_id=session_id,
            )
            if query_memory is None and not any((domain, work_product, user_intent)):
                raise ValueError(f"Unknown session summary: {session_id}")

        query_fields = {
            "domain": _clean_text(domain)
            or (query_memory.domain if query_memory is not None else None),
            "work_product": _clean_text(work_product)
            or (query_memory.work_product if query_memory is not None else None),
            "user_intent": _clean_text(user_intent)
            or (query_memory.user_intent if query_memory is not None else None),
        }
        populated_fields = {
            field_type: value
            for field_type, value in query_fields.items()
            if value
        }
        if not populated_fields:
            return ()

        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        for field_type, value in populated_fields.items():
            for search_value in _field_search_values(field_type=field_type, value=value):
                matches = await self.search_session_summaries_by_field(
                    vault_name=vault_name,
                    field_type=field_type,
                    value=search_value,
                    vector_service=vector_service,
                    vector_store=vector_store,
                    limit=max(limit * 4, limit),
                    min_score=RELATED_SESSION_FIELD_MIN_SCORE,
                    model_alias=model_alias,
                )
                weight = RELATED_SESSION_FIELD_WEIGHTS[field_type]
                for match in matches:
                    memory = match.session_summary
                    if query_memory is not None and memory.session_id == query_memory.session_id:
                        continue
                    key = (memory.session_id, memory.vault_name)
                    candidate = candidates.setdefault(
                        key,
                        {
                            "session_summary": memory,
                            "field_scores": {},
                            "contributions": [],
                        },
                    )
                    field_score = float(match.score or 0.0)
                    weighted_score = weight * field_score
                    candidate["field_scores"][field_type] = max(
                        float(candidate["field_scores"].get(field_type, 0.0)),
                        weighted_score,
                    )
                    candidate["contributions"].append(
                        RelatedSessionContribution(
                            field_type=field_type,
                            match_type=match.match_type,
                            score=round(field_score, 6),
                            weight=weight,
                            weighted_score=round(weighted_score, 6),
                            query_value=search_value,
                            matched_value=memory.field_value(field_type),
                        )
                    )

        results: list[RelatedSessionResult] = []
        for candidate in candidates.values():
            score = round(sum(float(value) for value in candidate["field_scores"].values()), 6)
            if score < min_score:
                continue
            contributions = tuple(
                sorted(
                    candidate["contributions"],
                    key=lambda contribution: contribution.weighted_score,
                    reverse=True,
                )
            )
            results.append(
                RelatedSessionResult(
                    session_summary=candidate["session_summary"],
                    band=_related_session_band(score),
                    score=score,
                    matched_field_count=len(candidate["field_scores"]),
                    contributions=contributions,
                )
            )
        results.sort(
            key=lambda result: (result.score, result.matched_field_count),
            reverse=True,
        )
        return tuple(results[:limit])

    async def index_session_summary_fields(
        self,
        *,
        vault_name: str,
        session_id: str,
        vector_service: VectorService,
        vector_store: VectorStore | None = None,
        model_alias: str = "embeddings",
    ) -> int:
        """Embed vector-searchable direct fields for one session summary."""
        session_summary = self.get_session_summary(vault_name=vault_name, session_id=session_id)
        if session_summary is None:
            raise ValueError(f"Unknown session summary: {session_id}")
        store = vector_store or self._field_vector_store()
        self._delete_field_vectors(
            vault_name=vault_name,
            session_id=session_id,
            vector_store=store,
        )
        fields = tuple(
            field_type
            for field_type in SESSION_SUMMARY_TEXT_FIELDS
            if field_type in VECTOR_FIELD_TYPES and session_summary.field_value(field_type)
        )
        if not fields:
            return 0

        inputs = [
            _field_embedding_text(
                field_type=field_type,
                value=_field_index_value(
                    field_type=field_type,
                    value=session_summary.field_value(field_type) or "",
                ),
            )
            for field_type in fields
        ]
        embedding_result = await vector_service.embed_documents(inputs, model_alias=model_alias)
        for field_type, embedding in zip(fields, embedding_result.vectors, strict=True):
            value = session_summary.field_value(field_type) or ""
            store.upsert(
                namespace=FIELD_VECTOR_NAMESPACE,
                item_id=f"{session_summary.vault_name}:{session_summary.session_id}:{field_type}",
                embedding=embedding,
                metadata={
                    "session_id": session_summary.session_id,
                    "vault_name": session_summary.vault_name,
                    "field_type": field_type,
                    "field_value": value,
                    "normalized_value": normalize_field_value(value),
                },
            )
        return len(fields)

    def _delete_field_vectors(
        self,
        *,
        vault_name: str,
        session_id: str,
        vector_store: VectorStore | None = None,
    ) -> None:
        store = vector_store or self._field_vector_store()
        item_ids = tuple(
            f"{vault_name}:{session_id}:{field_type}"
            for field_type in VECTOR_FIELD_TYPES
        )
        store.delete_items(namespace=FIELD_VECTOR_NAMESPACE, item_ids=item_ids)

    def _connect(self) -> sqlite3.Connection:
        ensure_session_summary_schema(self.system_root)
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

    def _upsert_fts_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        conn.execute(
            """
            DELETE FROM session_summaries_fts
            WHERE session_id = ? AND vault_name = ?
            """,
            (row["session_id"], row["vault_name"]),
        )
        conn.execute(
            """
            INSERT INTO session_summaries_fts (
                session_id, vault_name, title, summary, domain,
                work_product, user_intent, named_entities
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["session_id"],
                row["vault_name"],
                row["title"] or "",
                row["summary"] or "",
                row["domain"] or "",
                row["work_product"] or "",
                row["user_intent"] or "",
                row["named_entities"] or "",
            ),
        )

    def _session_summary_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> SessionSummary:
        session_id = str(row["session_id"])
        vault_name = str(row["vault_name"])
        return SessionSummary(
            session_id=session_id,
            vault_name=vault_name,
            title=_optional_text(row["title"]),
            summary=_optional_text(row["summary"]),
            domain=_optional_text(row["domain"]),
            work_product=_optional_text(row["work_product"]),
            user_intent=_optional_text(row["user_intent"]),
            named_entities=_optional_text(row["named_entities"]),
            source_summary=_optional_text(row["source_summary"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            metadata=_load_json(row["metadata_json"]),
            artifacts=self._artifacts_for_session(
                conn,
                vault_name=vault_name,
                session_id=session_id,
            ),
        )

    def _artifacts_for_session(
        self,
        conn: sqlite3.Connection,
        *,
        vault_name: str,
        session_id: str,
    ) -> tuple[SessionSummaryArtifact, ...]:
        rows = conn.execute(
            """
            SELECT vault_name, path, artifact_role, metadata_json
            FROM session_summary_artifacts
            WHERE session_id = ? AND vault_name = ?
            ORDER BY path ASC, artifact_role ASC
            """,
            (session_id, vault_name),
        ).fetchall()
        return tuple(
            SessionSummaryArtifact(
                vault_name=str(row["vault_name"]),
                path=str(row["path"]),
                artifact_role=str(row["artifact_role"]),
                metadata=_load_json(row["metadata_json"]),
            )
            for row in rows
        )

    def _session_summary_exists(
        self,
        conn: sqlite3.Connection,
        *,
        vault_name: str,
        session_id: str,
    ) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM session_summaries
            WHERE session_id = ? AND vault_name = ?
            LIMIT 1
            """,
            (session_id, vault_name),
        ).fetchone()
        return row is not None

    @staticmethod
    def _session_summary_select_columns(alias: str | None = None) -> str:
        columns = (
            "session_id",
            "vault_name",
            "title",
            "summary",
            "domain",
            "work_product",
            "user_intent",
            "named_entities",
            "source_summary",
            "created_at",
            "updated_at",
            "metadata_json",
        )
        if alias:
            return ", ".join(f"{alias}.{column}" for column in columns)
        return ", ".join(columns)


def normalize_field_value(value: str) -> str:
    """Normalize a field value for vector metadata and diagnostics."""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def build_fts_query(value: str, *, max_terms: int = 12) -> str:
    """Build a tolerant FTS5 query from LLM-shaped search text."""
    terms = _fts_query_terms(value, max_terms=max_terms)
    return " OR ".join(_quote_fts_phrase(term) for term in terms)


def _fts_query_terms(value: str, *, max_terms: int = 12) -> list[str]:
    phrases = [
        phrase.strip().lower()
        for phrase in re.findall(r'"([^"]+)"', value)
        if phrase.strip()
    ]
    without_phrases = re.sub(r'"[^"]+"', " ", value)
    tokens = [
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9-]{1,}", without_phrases)
    ]
    parts = [*phrases, *tokens]
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
        if len(deduped) >= max_terms:
            break
    return deduped


def _fts_query_coverage(query: str, session_summary: SessionSummary) -> float:
    terms = _fts_query_terms(query)
    if not terms:
        return 0.0
    haystack = " ".join(
        value.lower()
        for value in (
            session_summary.title,
            session_summary.summary,
            session_summary.domain,
            session_summary.work_product,
            session_summary.user_intent,
            session_summary.named_entities,
        )
        if value
    )
    matched = sum(1 for term in terms if term in haystack)
    return round(matched / len(terms), 6)


def _quote_fts_phrase(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _bm25_score(rank: float) -> float:
    score = min(abs(rank) / 10.0, 1.0)
    if rank != 0.0:
        score = max(score, 0.000001)
    return round(score, 6)


def _field_embedding_text(*, field_type: str, value: str) -> str:
    return f"{field_type}: {value}"


def _field_index_value(*, field_type: str, value: str) -> str:
    if field_type != "domain":
        return value
    return "\n".join(_domain_search_values(value))


def _field_search_values(*, field_type: str, value: str) -> tuple[str, ...]:
    if field_type != "domain":
        return (value,)
    return _domain_search_values(value)


def _domain_search_values(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    deduped: list[str] = []
    seen_normalized: set[str] = set()
    for part in re.split(r"\s*;\s*", value):
        domain = part.strip()
        normalized = normalize_field_value(domain)
        if not normalized or normalized in seen_normalized:
            continue
        deduped.append(domain)
        seen_normalized.add(normalized)
    return tuple(deduped)


def _validate_field_type(field_type: str) -> None:
    if field_type not in SESSION_SUMMARY_TEXT_FIELDS:
        allowed = ", ".join(SESSION_SUMMARY_TEXT_FIELDS)
        raise ValueError(f"Unsupported session summary field_type '{field_type}'. Allowed: {allowed}")


def _direct_match_type(field_type: str) -> str:
    return "wildcard" if field_type in WILDCARD_FIELD_TYPES else "substring"


def _related_session_band(score: float) -> str:
    if score >= RELATED_SESSION_AUTOMATIC_THRESHOLD:
        return "automatic_recommendation"
    if score >= RELATED_SESSION_POSSIBLE_THRESHOLD:
        return "possible_related"
    return "below_threshold"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _is_upsert_value_supplied(value: object) -> bool:
    return value is not SESSION_SUMMARY_FIELD_UNSET


def _clean_upsert_text(value: SessionSummaryTextInput) -> str | None:
    if value is SESSION_SUMMARY_FIELD_UNSET:
        return None
    return _clean_text(value)


def _dump_upsert_metadata(value: SessionSummaryMetadataInput) -> str | None:
    if value is SESSION_SUMMARY_FIELD_UNSET or value is None:
        return None
    return _dump_json(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True)


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}
