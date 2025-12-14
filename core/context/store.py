from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any

from core.context.templates import TemplateRecord
from core.database import get_system_database_path
from core.logger import UnifiedLogger

logger = UnifiedLogger(tag="context-store")


DB_NAME = "context_compiler"


def _get_db_path(system_root: Optional[Path] = None) -> str:
    return get_system_database_path(DB_NAME, str(system_root) if system_root else None)


def _ensure_db(system_root: Optional[Path] = None) -> str:
    """Create database file and tables if missing."""
    db_path = _get_db_path(system_root)
    conn = sqlite3.connect(db_path)
    try:
        # Drop/replace legacy micro-log schema if shape has changed
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='context_micro_log'"
        ).fetchone()
        if existing:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(context_micro_log)")}
            expected = {
                "id",
                "session_id",
                "vault_name",
                "turn_index",
                "summary_id",
                "canonical_topic",
                "stable_count",
                "user_input_snippet",
                "embedding_json",
                "created_at",
            }
            if columns != expected:
                conn.execute("DROP TABLE IF EXISTS context_micro_log")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, vault_name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS context_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                turn_index INTEGER,
                template_name TEXT,
                template_source TEXT,
                template_hash TEXT,
                model_alias TEXT,
                summary_json TEXT,
                raw_output TEXT,
                budget_used INTEGER,
                sections_included TEXT,
                compiled_prompt TEXT,
                input_payload TEXT,
                canonical_topic TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_context_summaries_session ON context_summaries(session_id, vault_name)"
        )
        # Ensure canonical_topic exists for existing databases
        columns = {row[1] for row in conn.execute("PRAGMA table_info(context_summaries)")}
        if "canonical_topic" not in columns:
            conn.execute("ALTER TABLE context_summaries ADD COLUMN canonical_topic TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS context_micro_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                turn_index INTEGER,
                summary_id INTEGER,
                canonical_topic TEXT,
                stable_count INTEGER DEFAULT 1,
                user_input_snippet TEXT,
                embedding_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(summary_id) REFERENCES context_summaries(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_micro_log_session ON context_micro_log(session_id, vault_name, id)"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def upsert_session(
    session_id: str,
    vault_name: str,
    metadata: Optional[Dict[str, Any]] = None,
    system_root: Optional[Path] = None,
) -> None:
    """Insert session row if missing; ignore duplicates."""
    db_path = _ensure_db(system_root)
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO sessions (session_id, vault_name, metadata)
            VALUES (?, ?, ?)
            """,
            (session_id, vault_name, meta_json),
        )
        conn.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to upsert session {session_id}: {exc}")
        raise
    finally:
        conn.close()


def add_context_summary(
    session_id: str,
    vault_name: str,
    turn_index: Optional[int],
    template: TemplateRecord,
    model_alias: str,
    summary_json: Optional[Dict[str, Any]],
    raw_output: Optional[str],
    budget_used: Optional[int] = None,
    sections_included: Optional[Dict[str, Any]] = None,
    compiled_prompt: Optional[str] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    system_root: Optional[Path] = None,
) -> int:
    """Persist a compiled context summary and return its row id."""
    db_path = _ensure_db(system_root)
    summary_str = json.dumps(summary_json, ensure_ascii=False) if summary_json is not None else None
    sections_str = json.dumps(sections_included, ensure_ascii=False) if sections_included is not None else None
    payload_str = json.dumps(input_payload, ensure_ascii=False) if input_payload is not None else None
    canonical_topic = _derive_canonical_topic(summary_json, input_payload)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO context_summaries (
                session_id,
                vault_name,
                turn_index,
                template_name,
                template_source,
                template_hash,
                model_alias,
                summary_json,
                raw_output,
                budget_used,
                sections_included,
                compiled_prompt,
                input_payload,
                canonical_topic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                vault_name,
                turn_index,
                template.name,
                template.source,
                template.sha256,
                model_alias,
                summary_str,
                raw_output,
                budget_used,
                sections_str,
                compiled_prompt,
                payload_str,
                canonical_topic,
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to insert context summary for session {session_id}: {exc}")
        raise
    finally:
        conn.close()


def get_latest_summary(
    session_id: str,
    vault_name: str,
    system_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch the most recent parsed summary JSON for a session/vault."""
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT summary_json
            FROM context_summaries
            WHERE session_id = ? AND vault_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id, vault_name),
        ).fetchone()
        if not row or not row[0]:
            return None
        return json.loads(row[0])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to fetch latest context summary for session {session_id}: {exc}")
        return None
    finally:
        conn.close()


def get_recent_summaries(
    session_id: str,
    vault_name: str,
    limit: int = 5,
    system_root: Optional[Path] = None,
) -> list[Dict[str, Any]]:
    """
    Fetch recent compiled summaries for a session/vault.

    Returns a compact list of snapshots so tools can compare the current turn
    with prior objectives/constraints without pulling full transcripts.
    """
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                turn_index,
                template_name,
                template_hash,
                model_alias,
                summary_json,
                raw_output,
                compiled_prompt,
                input_payload,
                canonical_topic,
                created_at
            FROM context_summaries
            WHERE session_id = ? AND vault_name = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, vault_name, limit),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to fetch recent context summaries for session {session_id}: {exc}")
        return []
    finally:
        conn.close()

    snapshots: list[Dict[str, Any]] = []
    for row in rows:
        summary_json = None
        input_payload = None
        try:
            summary_json = json.loads(row[4]) if row[4] else None
        except Exception:
            summary_json = None
        try:
            input_payload = json.loads(row[7]) if row[7] else None
        except Exception:
            input_payload = None

        snapshots.append(
            {
                "turn_index": row[0],
                "template_name": row[1],
                "template_hash": row[2],
                "model_alias": row[3],
                "summary": summary_json,
                "raw_output": row[5],
                "compiled_prompt": row[6],
                "input_payload": input_payload,
                "canonical_topic": row[8],
                "created_at": row[9],
            }
        )

    return snapshots


def fetch_summaries_without_micro_log(
    limit: int = 50,
    system_root: Optional[Path] = None,
) -> list[Dict[str, Any]]:
    """Fetch summaries that do not yet have a micro-log entry."""
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT cs.id, cs.session_id, cs.vault_name, cs.turn_index,
                   cs.summary_json, cs.input_payload, cs.raw_output, cs.compiled_prompt, cs.canonical_topic
            FROM context_summaries cs
            WHERE NOT EXISTS (
                SELECT 1 FROM context_micro_log ml
                WHERE ml.summary_id = cs.id
            )
            ORDER BY cs.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    results: list[Dict[str, Any]] = []
    for row in rows:
        try:
            summary_json = json.loads(row[4]) if row[4] else None
        except Exception:
            summary_json = None
        try:
            input_payload = json.loads(row[5]) if row[5] else None
        except Exception:
            input_payload = None

        results.append(
            {
                "id": row[0],
                "session_id": row[1],
                "vault_name": row[2],
                "turn_index": row[3],
                "summary_json": summary_json,
                "input_payload": input_payload,
                "raw_output": row[6],
                "compiled_prompt": row[7],
                "canonical_topic": row[8],
            }
        )
    return results


def update_canonical_topic(
    summary_id: int,
    canonical_topic: Optional[str],
    system_root: Optional[Path] = None,
) -> None:
    """Update canonical_topic for a summary row."""
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            UPDATE context_summaries
            SET canonical_topic = ?
            WHERE id = ?
            """,
            (canonical_topic, summary_id),
        )
        conn.commit()
    finally:
        conn.close()


def add_micro_log_entry(
    session_id: str,
    vault_name: str,
    turn_index: Optional[int],
    summary_id: int,
    user_input_snippet: str | None,
    canonical_topic: Optional[str],
    embedding: Optional[list[float]] = None,
    system_root: Optional[Path] = None,
) -> None:
    """Add or coalesce a micro-log entry pointing to a compiled summary."""
    db_path = _ensure_db(system_root)
    embedding_json = json.dumps(embedding) if embedding else None

    conn = sqlite3.connect(db_path)
    try:
        last = conn.execute(
            """
            SELECT id, canonical_topic, stable_count
            FROM context_micro_log
            WHERE session_id = ? AND vault_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id, vault_name),
        ).fetchone()

        if canonical_topic and last and last[1] == canonical_topic:
            conn.execute(
                """
                UPDATE context_micro_log
                SET stable_count = ?, user_input_snippet = ?, embedding_json = ?
                WHERE id = ?
                """,
                (int(last[2] or 1) + 1, (user_input_snippet or "")[:400], embedding_json, last[0]),
            )
            conn.commit()
            return

        conn.execute(
            """
            INSERT INTO context_micro_log (
                session_id,
                vault_name,
                turn_index,
                summary_id,
                canonical_topic,
                stable_count,
                user_input_snippet,
                embedding_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                vault_name,
                turn_index,
                summary_id,
                canonical_topic,
                1,
                (user_input_snippet or "")[:400],
                embedding_json,
            ),
        )
        conn.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to insert micro-log for session {session_id}: {exc}")
        raise
    finally:
        conn.close()


def get_recent_micro_log(
    session_id: str,
    vault_name: str,
    limit: int = 5,
    system_root: Optional[Path] = None,
) -> list[Dict[str, Any]]:
    """Fetch recent micro-log entries (newest first)."""
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, turn_index, summary_id, canonical_topic, stable_count, user_input_snippet, embedding_json, created_at
            FROM context_micro_log
            WHERE session_id = ? AND vault_name = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, vault_name, limit),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to fetch micro-log for session {session_id}: {exc}")
        return []
    finally:
        conn.close()

    entries: list[Dict[str, Any]] = []
    for row in rows:
        embedding = None
        try:
            embedding = json.loads(row[6]) if row[6] else None
        except Exception:
            embedding = None

        entries.append(
            {
                "id": row[0],
                "turn_index": row[1],
                "summary_id": row[2],
                "canonical_topic": row[3],
                "stable_count": row[4],
                "user_input_snippet": row[5],
                "embedding": embedding,
                "created_at": row[7],
            }
        )
    return entries


def get_summary_by_id(
    summary_id: int,
    system_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch a compiled summary row by id."""
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT summary_json, raw_output, compiled_prompt, input_payload, canonical_topic
            FROM context_summaries
            WHERE id = ?
            LIMIT 1
            """,
            (summary_id,),
        ).fetchone()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to fetch summary {summary_id}: {exc}")
        return None
    finally:
        conn.close()

    if not row:
        return None

    def _maybe_load(value: Optional[str]):
        try:
            return json.loads(value) if value else None
        except Exception:
            return value

    return {
        "summary": _maybe_load(row[0]),
        "raw_output": row[1],
        "compiled_prompt": row[2],
        "input_payload": _maybe_load(row[3]),
        "canonical_topic": row[4],
    }
