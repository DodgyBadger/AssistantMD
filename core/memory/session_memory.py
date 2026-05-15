"""Session memory persistence and field-aware retrieval."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.database import connect_sqlite_from_system_db
from core.memory.schema import DB_NAME, ensure_memory_schema
from core.vector import SQLitePythonVectorStore, VectorService, VectorStore


SESSION_MEMORY_TEXT_FIELDS = (
    "summary",
    "domain",
    "work_product",
    "user_intent",
    "named_entities",
)
VECTOR_FIELD_TYPES = {"summary", "domain", "work_product", "user_intent"}
WILDCARD_FIELD_TYPES = {"named_entities"}
FIELD_VECTOR_NAMESPACE = "session_memory_fields"
FIELD_VECTOR_TABLE = "session_memory_field_vectors"
RELATED_SESSION_FIELD_WEIGHTS = {
    "domain": 0.45,
    "work_product": 0.35,
    "user_intent": 0.20,
}
RELATED_SESSION_FIELD_MIN_SCORE = 0.40
RELATED_SESSION_AUTOMATIC_THRESHOLD = 0.70
RELATED_SESSION_POSSIBLE_THRESHOLD = 0.55


@dataclass(frozen=True)
class SessionMemoryArtifact:
    """One vault artifact associated with a chat session memory."""

    path: str
    artifact_role: str
    vault_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class SessionMemory:
    """Stored memory extracted from one chat session."""

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
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[SessionMemoryArtifact, ...] = ()

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    def field_value(self, field_type: str) -> str | None:
        """Return a queryable session memory field value by name."""
        _validate_field_type(field_type)
        value = getattr(self, field_type)
        return str(value) if value else None


@dataclass(frozen=True)
class SessionMemorySearchResult:
    """One field-aware session memory search result."""

    session_memory: SessionMemory
    match_type: str
    matched_fields: tuple[dict[str, Any], ...]
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "session_memory": self.session_memory.to_dict(),
            "match_type": self.match_type,
            "matched_fields": list(self.matched_fields),
            "score": self.score,
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

    session_memory: SessionMemory
    band: str
    score: float
    matched_field_count: int
    contributions: tuple[RelatedSessionContribution, ...]

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "session_memory": self.session_memory.to_dict(),
            "band": self.band,
            "score": self.score,
            "matched_field_count": self.matched_field_count,
            "contributions": [
                contribution.to_dict()
                for contribution in self.contributions
            ],
        }


class SessionMemoryStore:
    """SQLite-backed store for session memory."""

    def __init__(self, system_root: str | None = None):
        self.system_root = system_root
        ensure_memory_schema(system_root)

    def upsert_session_memory(
        self,
        *,
        vault_name: str,
        session_id: str,
        title: str | None = None,
        summary: str | None = None,
        domain: str | None = None,
        work_product: str | None = None,
        user_intent: str | None = None,
        named_entities: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMemory:
        """Create or replace the memory fields for one chat session."""
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_memories (
                    session_id, vault_name, title,
                    summary, domain, work_product, user_intent, named_entities,
                    created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, vault_name)
                DO UPDATE SET
                    title = COALESCE(excluded.title, session_memories.title),
                    summary = COALESCE(excluded.summary, session_memories.summary),
                    domain = COALESCE(excluded.domain, session_memories.domain),
                    work_product = COALESCE(excluded.work_product, session_memories.work_product),
                    user_intent = COALESCE(excluded.user_intent, session_memories.user_intent),
                    named_entities = COALESCE(
                        excluded.named_entities,
                        session_memories.named_entities
                    ),
                    updated_at = excluded.updated_at,
                    metadata_json = COALESCE(
                        excluded.metadata_json,
                        session_memories.metadata_json
                    )
                """,
                (
                    session_id,
                    vault_name,
                    _clean_text(title),
                    _clean_text(summary),
                    _clean_text(domain),
                    _clean_text(work_product),
                    _clean_text(user_intent),
                    _clean_text(named_entities),
                    now,
                    now,
                    _dump_json(metadata) if metadata is not None else None,
                ),
            )
        session_memory = self.get_session_memory(
            vault_name=vault_name,
            session_id=session_id,
        )
        if session_memory is None:
            raise RuntimeError(f"Failed to upsert session memory {session_id}")
        return session_memory

    def get_session_memory(
        self,
        *,
        vault_name: str,
        session_id: str,
    ) -> SessionMemory | None:
        """Return one session memory by vault and session id."""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self._session_memory_select_columns()}
                FROM session_memories
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            if row is None:
                return None
            return self._session_memory_from_row(conn, row)

    def delete_session_memory(self, *, vault_name: str, session_id: str) -> bool:
        """Delete one session memory row and associated artifacts."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM session_memories
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )
            return cursor.rowcount > 0

    def add_session_artifacts(
        self,
        *,
        vault_name: str,
        session_id: str,
        artifacts: list[SessionMemoryArtifact] | tuple[SessionMemoryArtifact, ...],
    ) -> None:
        """Upsert vault artifacts for one session memory."""
        with self._connect() as conn:
            if not self._session_memory_exists(conn, vault_name=vault_name, session_id=session_id):
                raise ValueError(f"Unknown session memory: {session_id}")
            now = _utc_now()
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO session_memory_artifacts (
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

    def search_session_memories(
        self,
        *,
        vault_name: str,
        field_type: str | None = None,
        value: str | None = None,
        limit: int = 20,
    ) -> tuple[SessionMemory, ...]:
        """Search session memories by vault and optionally one direct field value."""
        with self._connect() as conn:
            if field_type and value:
                _validate_field_type(field_type)
                if field_type in WILDCARD_FIELD_TYPES:
                    where_clause = f"lower({field_type}) LIKE ? ESCAPE '\\'"
                    field_value = f"%{_escape_like(value.lower())}%"
                else:
                    where_clause = f"{field_type} IS NOT NULL AND lower(trim({field_type})) = ?"
                    field_value = value.lower().strip()
                rows = conn.execute(
                    f"""
                    SELECT {self._session_memory_select_columns()}
                    FROM session_memories
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
                    SELECT {self._session_memory_select_columns()}
                    FROM session_memories
                    WHERE vault_name = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (vault_name, limit),
                ).fetchall()
            return tuple(self._session_memory_from_row(conn, row) for row in rows)

    async def search_session_memories_by_field(
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
    ) -> tuple[SessionMemorySearchResult, ...]:
        """Search one session memory field using exact/wildcard plus vectors."""
        _validate_field_type(field_type)
        exact_matches = self.search_session_memories(
            vault_name=vault_name,
            field_type=field_type,
            value=value,
            limit=limit,
        )
        results: dict[tuple[str, str], SessionMemorySearchResult] = {
            (memory.session_id, memory.vault_name): SessionMemorySearchResult(
                session_memory=memory,
                match_type="exact" if field_type not in WILDCARD_FIELD_TYPES else "wildcard",
                matched_fields=(
                    {
                        "field_type": field_type,
                        "query_value": value,
                        "matched_value": memory.field_value(field_type),
                        "match_type": "exact"
                        if field_type not in WILDCARD_FIELD_TYPES
                        else "wildcard",
                    },
                ),
                score=1.0,
            )
            for memory in exact_matches
        }

        if field_type not in VECTOR_FIELD_TYPES or len(results) >= limit:
            return tuple(results.values())[:limit]

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
            key = (session_id, vault_name)
            if not session_id or key in results:
                continue
            session_memory = self.get_session_memory(
                vault_name=vault_name,
                session_id=session_id,
            )
            if session_memory is None:
                continue
            current_value = session_memory.field_value(field_type)
            if not current_value:
                continue
            results[key] = SessionMemorySearchResult(
                session_memory=session_memory,
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
            if len(results) >= limit:
                break
        return tuple(results.values())

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
        """Find related session memories using the current compound policy."""
        if limit <= 0:
            return ()
        query_memory: SessionMemory | None = None
        if session_id:
            query_memory = self.get_session_memory(
                vault_name=vault_name,
                session_id=session_id,
            )
            if query_memory is None and not any((domain, work_product, user_intent)):
                raise ValueError(f"Unknown session memory: {session_id}")

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
            matches = await self.search_session_memories_by_field(
                vault_name=vault_name,
                field_type=field_type,
                value=value,
                vector_service=vector_service,
                vector_store=vector_store,
                limit=max(limit * 4, limit),
                min_score=RELATED_SESSION_FIELD_MIN_SCORE,
                model_alias=model_alias,
            )
            weight = RELATED_SESSION_FIELD_WEIGHTS[field_type]
            for match in matches:
                memory = match.session_memory
                if query_memory is not None and memory.session_id == query_memory.session_id:
                    continue
                key = (memory.session_id, memory.vault_name)
                candidate = candidates.setdefault(
                    key,
                    {
                        "session_memory": memory,
                        "score": 0.0,
                        "contributions": [],
                    },
                )
                field_score = float(match.score or 0.0)
                weighted_score = weight * field_score
                candidate["score"] += weighted_score
                candidate["contributions"].append(
                    RelatedSessionContribution(
                        field_type=field_type,
                        match_type=match.match_type,
                        score=round(field_score, 6),
                        weight=weight,
                        weighted_score=round(weighted_score, 6),
                        query_value=value,
                        matched_value=memory.field_value(field_type),
                    )
                )

        results: list[RelatedSessionResult] = []
        for candidate in candidates.values():
            score = round(float(candidate["score"]), 6)
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
                    session_memory=candidate["session_memory"],
                    band=_related_session_band(score),
                    score=score,
                    matched_field_count=len(contributions),
                    contributions=contributions,
                )
            )
        results.sort(
            key=lambda result: (result.score, result.matched_field_count),
            reverse=True,
        )
        return tuple(results[:limit])

    async def index_session_memory_fields(
        self,
        *,
        vault_name: str,
        session_id: str,
        vector_service: VectorService,
        vector_store: VectorStore | None = None,
        model_alias: str = "embeddings",
    ) -> int:
        """Embed vector-searchable direct fields for one session memory."""
        session_memory = self.get_session_memory(vault_name=vault_name, session_id=session_id)
        if session_memory is None:
            raise ValueError(f"Unknown session memory: {session_id}")
        fields = tuple(
            field_type
            for field_type in SESSION_MEMORY_TEXT_FIELDS
            if field_type in VECTOR_FIELD_TYPES and session_memory.field_value(field_type)
        )
        if not fields:
            return 0

        store = vector_store or self._field_vector_store()
        inputs = [
            _field_embedding_text(
                field_type=field_type,
                value=session_memory.field_value(field_type) or "",
            )
            for field_type in fields
        ]
        embedding_result = await vector_service.embed_documents(inputs, model_alias=model_alias)
        for field_type, embedding in zip(fields, embedding_result.vectors, strict=True):
            value = session_memory.field_value(field_type) or ""
            store.upsert(
                namespace=FIELD_VECTOR_NAMESPACE,
                item_id=f"{session_memory.vault_name}:{session_memory.session_id}:{field_type}",
                embedding=embedding,
                metadata={
                    "session_id": session_memory.session_id,
                    "vault_name": session_memory.vault_name,
                    "field_type": field_type,
                    "field_value": value,
                    "normalized_value": normalize_field_value(value),
                },
            )
        return len(fields)

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

    def _session_memory_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> SessionMemory:
        session_id = str(row["session_id"])
        vault_name = str(row["vault_name"])
        return SessionMemory(
            session_id=session_id,
            vault_name=vault_name,
            title=_optional_text(row["title"]),
            summary=_optional_text(row["summary"]),
            domain=_optional_text(row["domain"]),
            work_product=_optional_text(row["work_product"]),
            user_intent=_optional_text(row["user_intent"]),
            named_entities=_optional_text(row["named_entities"]),
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
    ) -> tuple[SessionMemoryArtifact, ...]:
        rows = conn.execute(
            """
            SELECT vault_name, path, artifact_role, metadata_json
            FROM session_memory_artifacts
            WHERE session_id = ? AND vault_name = ?
            ORDER BY path ASC, artifact_role ASC
            """,
            (session_id, vault_name),
        ).fetchall()
        return tuple(
            SessionMemoryArtifact(
                vault_name=str(row["vault_name"]),
                path=str(row["path"]),
                artifact_role=str(row["artifact_role"]),
                metadata=_load_json(row["metadata_json"]),
            )
            for row in rows
        )

    def _session_memory_exists(
        self,
        conn: sqlite3.Connection,
        *,
        vault_name: str,
        session_id: str,
    ) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM session_memories
            WHERE session_id = ? AND vault_name = ?
            LIMIT 1
            """,
            (session_id, vault_name),
        ).fetchone()
        return row is not None

    @staticmethod
    def _session_memory_select_columns(alias: str | None = None) -> str:
        columns = (
            "session_id",
            "vault_name",
            "title",
            "summary",
            "domain",
            "work_product",
            "user_intent",
            "named_entities",
            "created_at",
            "updated_at",
            "metadata_json",
        )
        if alias:
            return ", ".join(f"{alias}.{column}" for column in columns)
        return ", ".join(columns)


def normalize_field_value(value: str) -> str:
    """Normalize a field value for exact lookup."""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _field_embedding_text(*, field_type: str, value: str) -> str:
    return f"{field_type}: {value}"


def _validate_field_type(field_type: str) -> None:
    if field_type not in SESSION_MEMORY_TEXT_FIELDS:
        allowed = ", ".join(SESSION_MEMORY_TEXT_FIELDS)
        raise ValueError(f"Unsupported session memory field_type '{field_type}'. Allowed: {allowed}")


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
