"""Workstream memory persistence and field-aware retrieval."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.database import connect_sqlite_from_system_db
from core.memory.schema import DB_NAME, ensure_memory_schema
from core.vector import SQLitePythonVectorStore, VectorService, VectorStore


WORKSTREAM_TEXT_FIELDS = (
    "type",
    "topic",
    "entities",
    "project",
    "objective",
    "strategy",
)
VECTOR_FIELD_TYPES = {"type", "topic", "objective", "strategy"}
WILDCARD_FIELD_TYPES = {"entities", "project"}
FIELD_VECTOR_NAMESPACE = "workstream_fields"
FIELD_VECTOR_TABLE = "workstream_field_vectors"


@dataclass(frozen=True)
class WorkstreamArtifact:
    """One vault artifact associated with a workstream."""

    path: str
    artifact_role: str
    vault_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class Workstream:
    """Stored workstream with queryable text fields and artifacts."""

    workstream_id: str
    vault_name: str
    title: str | None
    status: str
    created_at: str
    last_seen_at: str
    type: str | None = None
    topic: str | None = None
    entities: str | None = None
    project: str | None = None
    objective: str | None = None
    strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[WorkstreamArtifact, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "workstream_id": self.workstream_id,
            "vault_name": self.vault_name,
            "title": self.title,
            "status": self.status,
            "type": self.type,
            "topic": self.topic,
            "entities": self.entities,
            "project": self.project,
            "objective": self.objective,
            "strategy": self.strategy,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "metadata": self.metadata,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    def field_value(self, field_type: str) -> str | None:
        """Return a queryable workstream field value by name."""
        _validate_field_type(field_type)
        value = getattr(self, field_type)
        return str(value) if value else None


@dataclass(frozen=True)
class WorkstreamSearchResult:
    """One field-aware workstream search result."""

    workstream: Workstream
    match_type: str
    matched_fields: tuple[dict[str, Any], ...]
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-compatible dictionary."""
        return {
            "workstream": self.workstream.to_dict(),
            "match_type": self.match_type,
            "matched_fields": list(self.matched_fields),
            "score": self.score,
        }


class WorkstreamStore:
    """SQLite-backed store for workstream memory."""

    def __init__(self, system_root: str | None = None):
        self.system_root = system_root
        ensure_memory_schema(system_root)

    def create_workstream(
        self,
        *,
        vault_name: str,
        title: str | None = None,
        workstream_id: str | None = None,
        status: str = "active",
        type: str | None = None,
        topic: str | None = None,
        entities: str | None = None,
        project: str | None = None,
        objective: str | None = None,
        strategy: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workstream:
        """Create and return a workstream without linking any session."""
        workstream_id = workstream_id or f"workstream-{uuid4().hex}"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workstreams (
                    workstream_id, vault_name, title, status,
                    type, topic, entities, project, objective, strategy,
                    created_at, last_seen_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workstream_id,
                    vault_name,
                    _clean_text(title),
                    status,
                    _clean_text(type),
                    _clean_text(topic),
                    _clean_text(entities),
                    _clean_text(project),
                    _clean_text(objective),
                    _clean_text(strategy),
                    now,
                    now,
                    _dump_json(metadata or {}),
                ),
            )
        workstream = self.get_workstream(workstream_id)
        if workstream is None:
            raise RuntimeError(f"Failed to create workstream {workstream_id}")
        return workstream

    def get_workstream(self, workstream_id: str) -> Workstream | None:
        """Return one workstream by id, including artifacts."""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self._workstream_select_columns()}
                FROM workstreams
                WHERE workstream_id = ?
                """,
                (workstream_id,),
            ).fetchone()
            if row is None:
                return None
            return self._workstream_from_row(conn, row)

    def get_current_workstream(
        self,
        *,
        vault_name: str,
        session_id: str,
    ) -> Workstream | None:
        """Return the workstream currently linked to a session, if any."""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self._workstream_select_columns("e")}
                FROM workstream_sessions s
                JOIN workstreams e ON e.workstream_id = s.workstream_id
                WHERE s.session_id = ? AND s.vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            if row is None:
                return None
            return self._workstream_from_row(conn, row)

    def link_session_to_workstream(
        self,
        *,
        workstream_id: str,
        vault_name: str,
        session_id: str,
    ) -> Workstream:
        """Link a session to one current workstream in the same vault."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT vault_name FROM workstreams WHERE workstream_id = ?",
                (workstream_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown workstream: {workstream_id}")
            if str(row["vault_name"]) != vault_name:
                raise ValueError("Cannot link a session to a workstream in another vault")
            now = _utc_now()
            conn.execute(
                """
                INSERT INTO workstream_sessions (
                    workstream_id, session_id, vault_name, linked_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, vault_name)
                DO UPDATE SET
                    workstream_id = excluded.workstream_id,
                    linked_at = excluded.linked_at
                """,
                (workstream_id, session_id, vault_name, now),
            )
            conn.execute(
                """
                UPDATE workstreams
                SET last_seen_at = ?
                WHERE workstream_id = ?
                """,
                (now, workstream_id),
            )
        workstream = self.get_workstream(workstream_id)
        if workstream is None:
            raise RuntimeError(f"Linked workstream disappeared: {workstream_id}")
        return workstream

    def update_workstream(
        self,
        *,
        workstream_id: str,
        title: str | None = None,
        status: str | None = None,
        type: str | None = None,
        topic: str | None = None,
        entities: str | None = None,
        project: str | None = None,
        objective: str | None = None,
        strategy: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workstream:
        """Update provided workstream columns and return the refreshed row."""
        updates: dict[str, Any] = {
            "title": title,
            "status": status,
            "type": type,
            "topic": topic,
            "entities": entities,
            "project": project,
            "objective": objective,
            "strategy": strategy,
        }
        set_parts: list[str] = []
        values: list[Any] = []
        for column, value in updates.items():
            if value is None:
                continue
            set_parts.append(f"{column} = ?")
            values.append(_clean_text(value) if column != "status" else value)
        if metadata is not None:
            set_parts.append("metadata_json = ?")
            values.append(_dump_json(metadata))
        set_parts.append("last_seen_at = ?")
        values.append(_utc_now())
        values.append(workstream_id)
        with self._connect() as conn:
            if not self._workstream_exists(conn, workstream_id):
                raise ValueError(f"Unknown workstream: {workstream_id}")
            conn.execute(
                f"""
                UPDATE workstreams
                SET {", ".join(set_parts)}
                WHERE workstream_id = ?
                """,
                tuple(values),
            )
        workstream = self.get_workstream(workstream_id)
        if workstream is None:
            raise RuntimeError(f"Updated workstream disappeared: {workstream_id}")
        return workstream

    def add_workstream_artifacts(
        self,
        *,
        workstream_id: str,
        artifacts: list[WorkstreamArtifact] | tuple[WorkstreamArtifact, ...],
    ) -> None:
        """Upsert vault artifacts for a workstream."""
        with self._connect() as conn:
            if not self._workstream_exists(conn, workstream_id):
                raise ValueError(f"Unknown workstream: {workstream_id}")
            now = _utc_now()
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO workstream_artifacts (
                        workstream_id, vault_name, path, artifact_role,
                        created_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workstream_id, path, artifact_role)
                    DO UPDATE SET
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        workstream_id,
                        artifact.vault_name,
                        artifact.path,
                        artifact.artifact_role,
                        now,
                        _dump_json(artifact.metadata),
                    ),
                )

    def list_workstream_artifacts(self, workstream_id: str) -> tuple[WorkstreamArtifact, ...]:
        """List artifacts for one workstream."""
        with self._connect() as conn:
            return self._artifacts_for_workstream(conn, workstream_id)

    def search_workstreams(
        self,
        *,
        vault_name: str,
        field_type: str | None = None,
        value: str | None = None,
        limit: int = 20,
    ) -> tuple[Workstream, ...]:
        """Search workstreams by vault and optionally one direct field value."""
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
                    SELECT {self._workstream_select_columns()}
                    FROM workstreams
                    WHERE vault_name = ?
                      AND {where_clause}
                    ORDER BY last_seen_at DESC
                    LIMIT ?
                    """,
                    (vault_name, field_value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT {self._workstream_select_columns()}
                    FROM workstreams
                    WHERE vault_name = ?
                    ORDER BY last_seen_at DESC
                    LIMIT ?
                    """,
                    (vault_name, limit),
                ).fetchall()
            return tuple(self._workstream_from_row(conn, row) for row in rows)

    async def search_workstreams_by_field(
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
    ) -> tuple[WorkstreamSearchResult, ...]:
        """Search one direct workstream field using exact/wildcard plus vectors."""
        _validate_field_type(field_type)
        exact_matches = self.search_workstreams(
            vault_name=vault_name,
            field_type=field_type,
            value=value,
            limit=limit,
        )
        results: dict[str, WorkstreamSearchResult] = {
            workstream.workstream_id: WorkstreamSearchResult(
                workstream=workstream,
                match_type="exact" if field_type not in WILDCARD_FIELD_TYPES else "wildcard",
                matched_fields=(
                    {
                        "field_type": field_type,
                        "query_value": value,
                        "matched_value": workstream.field_value(field_type),
                        "match_type": "exact"
                        if field_type not in WILDCARD_FIELD_TYPES
                        else "wildcard",
                    },
                ),
                score=1.0,
            )
            for workstream in exact_matches
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
            workstream_id = str(metadata.get("workstream_id") or "")
            if not workstream_id or workstream_id in results:
                continue
            workstream = self.get_workstream(workstream_id)
            if workstream is None:
                continue
            results[workstream_id] = WorkstreamSearchResult(
                workstream=workstream,
                match_type="semantic",
                matched_fields=(
                    {
                        "field_type": field_type,
                        "query_value": value,
                        "matched_value": workstream.field_value(field_type),
                        "match_type": "semantic",
                    },
                ),
                score=round(hit.score, 6),
            )
            if len(results) >= limit:
                break
        return tuple(results.values())

    async def index_workstream_fields(
        self,
        *,
        workstream_id: str,
        vector_service: VectorService,
        vector_store: VectorStore | None = None,
        model_alias: str = "embeddings",
    ) -> int:
        """Embed vector-searchable direct fields for one workstream."""
        workstream = self.get_workstream(workstream_id)
        if workstream is None:
            raise ValueError(f"Unknown workstream: {workstream_id}")
        fields = tuple(
            field_type
            for field_type in WORKSTREAM_TEXT_FIELDS
            if field_type in VECTOR_FIELD_TYPES and workstream.field_value(field_type)
        )
        if not fields:
            return 0

        store = vector_store or self._field_vector_store()
        inputs = [
            _field_embedding_text(
                field_type=field_type,
                value=workstream.field_value(field_type) or "",
            )
            for field_type in fields
        ]
        embedding_result = await vector_service.embed_documents(inputs, model_alias=model_alias)
        for field_type, embedding in zip(fields, embedding_result.vectors, strict=True):
            value = workstream.field_value(field_type) or ""
            store.upsert(
                namespace=FIELD_VECTOR_NAMESPACE,
                item_id=f"{workstream.workstream_id}:{field_type}",
                embedding=embedding,
                metadata={
                    "workstream_id": workstream.workstream_id,
                    "vault_name": workstream.vault_name,
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

    def _workstream_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Workstream:
        workstream_id = str(row["workstream_id"])
        return Workstream(
            workstream_id=workstream_id,
            vault_name=str(row["vault_name"]),
            title=_optional_text(row["title"]),
            status=str(row["status"]),
            type=_optional_text(row["type"]),
            topic=_optional_text(row["topic"]),
            entities=_optional_text(row["entities"]),
            project=_optional_text(row["project"]),
            objective=_optional_text(row["objective"]),
            strategy=_optional_text(row["strategy"]),
            created_at=str(row["created_at"]),
            last_seen_at=str(row["last_seen_at"]),
            metadata=_load_json(row["metadata_json"]),
            artifacts=self._artifacts_for_workstream(conn, workstream_id),
        )

    def _artifacts_for_workstream(
        self,
        conn: sqlite3.Connection,
        workstream_id: str,
    ) -> tuple[WorkstreamArtifact, ...]:
        rows = conn.execute(
            """
            SELECT vault_name, path, artifact_role, metadata_json
            FROM workstream_artifacts
            WHERE workstream_id = ?
            ORDER BY path ASC, artifact_role ASC
            """,
            (workstream_id,),
        ).fetchall()
        return tuple(
            WorkstreamArtifact(
                vault_name=str(row["vault_name"]),
                path=str(row["path"]),
                artifact_role=str(row["artifact_role"]),
                metadata=_load_json(row["metadata_json"]),
            )
            for row in rows
        )

    def _workstream_exists(self, conn: sqlite3.Connection, workstream_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM workstreams WHERE workstream_id = ? LIMIT 1",
            (workstream_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _workstream_select_columns(alias: str | None = None) -> str:
        columns = (
            "workstream_id",
            "vault_name",
            "title",
            "status",
            "type",
            "topic",
            "entities",
            "project",
            "objective",
            "strategy",
            "created_at",
            "last_seen_at",
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
    if field_type not in WORKSTREAM_TEXT_FIELDS:
        allowed = ", ".join(WORKSTREAM_TEXT_FIELDS)
        raise ValueError(f"Unsupported workstream field_type '{field_type}'. Allowed: {allowed}")


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
