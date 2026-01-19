from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any

from core.context.templates import TemplateRecord
from core.database import get_system_database_path
from core.logger import UnifiedLogger

logger = UnifiedLogger(tag="context-store")


DB_NAME = "cache"


def _get_db_path(system_root: Optional[Path] = None) -> str:
    return get_system_database_path(DB_NAME, str(system_root) if system_root else None)


def _ensure_db(system_root: Optional[Path] = None) -> str:
    """Create database file and tables if missing."""
    db_path = _get_db_path(system_root)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS context_step_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                template_name TEXT NOT NULL,
                template_hash TEXT NOT NULL,
                section_key TEXT NOT NULL,
                cache_mode TEXT NOT NULL,
                ttl_seconds INTEGER,
                raw_output TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_context_step_cache_lookup
            ON context_step_cache(vault_name, template_name, section_key)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_context_step_cache_run
            ON context_step_cache(run_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_context_step_cache_session
            ON context_step_cache(session_id)
            """
        )
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
                raw_output TEXT,
                budget_used INTEGER,
                sections_included TEXT,
                compiled_prompt TEXT,
                input_payload TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_context_summaries_session ON context_summaries(session_id, vault_name)"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def upsert_cached_step_output(
    *,
    run_id: str,
    session_id: str,
    vault_name: str,
    template_name: str,
    template_hash: str,
    section_key: str,
    cache_mode: str,
    ttl_seconds: Optional[int],
    raw_output: str,
    system_root: Optional[Path] = None,
) -> None:
    """Insert or update a cached step output."""
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        if cache_mode == "session":
            conn.execute(
                """
                DELETE FROM context_step_cache
                WHERE vault_name = ? AND template_name = ? AND section_key = ?
                  AND cache_mode = ? AND session_id = ?
                """,
                (vault_name, template_name, section_key, cache_mode, session_id),
            )
        else:
            conn.execute(
                """
                DELETE FROM context_step_cache
                WHERE vault_name = ? AND template_name = ? AND section_key = ?
                  AND cache_mode = ?
                """,
                (vault_name, template_name, section_key, cache_mode),
            )
        conn.execute(
            """
            INSERT INTO context_step_cache (
                run_id,
                session_id,
                vault_name,
                template_name,
                template_hash,
                section_key,
                cache_mode,
                ttl_seconds,
                raw_output
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                session_id,
                vault_name,
                template_name,
                template_hash,
                section_key,
                cache_mode,
                ttl_seconds,
                raw_output,
            ),
        )
        conn.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to upsert cached step output for {section_key}: {exc}")
        raise
    finally:
        conn.close()


def get_cached_step_output(
    *,
    session_id: str,
    vault_name: str,
    template_name: str,
    section_key: str,
    cache_mode: str,
    system_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch the most recent cached step output for a key."""
    db_path = _ensure_db(system_root)
    conn = sqlite3.connect(db_path)
    try:
        if cache_mode == "session":
            rows = conn.execute(
                """
                SELECT
                    run_id,
                    session_id,
                    vault_name,
                    template_name,
                    template_hash,
                    section_key,
                    cache_mode,
                    ttl_seconds,
                    raw_output,
                    created_at
                FROM context_step_cache
                WHERE vault_name = ? AND template_name = ? AND section_key = ?
                  AND cache_mode = ? AND session_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (vault_name, template_name, section_key, cache_mode, session_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    run_id,
                    session_id,
                    vault_name,
                    template_name,
                    template_hash,
                    section_key,
                    cache_mode,
                    ttl_seconds,
                    raw_output,
                    created_at
                FROM context_step_cache
                WHERE vault_name = ? AND template_name = ? AND section_key = ?
                  AND cache_mode = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (vault_name, template_name, section_key, cache_mode),
            ).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to fetch cached step output for {section_key}: {exc}")
        return None
    finally:
        conn.close()

    if not rows:
        return None

    row = rows[0]
    return {
        "run_id": row[0],
        "session_id": row[1],
        "vault_name": row[2],
        "template_name": row[3],
        "template_hash": row[4],
        "section_key": row[5],
        "cache_mode": row[6],
        "ttl_seconds": row[7],
        "raw_output": row[8],
        "created_at": row[9],
    }


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
    raw_output: Optional[str],
    budget_used: Optional[int] = None,
    sections_included: Optional[Dict[str, Any]] = None,
    compiled_prompt: Optional[str] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    system_root: Optional[Path] = None,
) -> int:
    """Persist a compiled context summary and return its row id."""
    db_path = _ensure_db(system_root)
    sections_str = json.dumps(sections_included, ensure_ascii=False) if sections_included is not None else None
    payload_str = json.dumps(input_payload, ensure_ascii=False) if input_payload is not None else None

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
                raw_output,
                budget_used,
                sections_included,
                compiled_prompt,
                input_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                vault_name,
                turn_index,
                template.name,
                template.source,
                template.sha256,
                model_alias,
                raw_output,
                budget_used,
                sections_str,
                compiled_prompt,
                payload_str,
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to insert context summary for session {session_id}: {exc}")
        raise
    finally:
        conn.close()


def get_recent_summaries(
    session_id: str,
    vault_name: str,
    limit: Optional[int] = 5,
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
        if limit is None:
            rows = conn.execute(
                """
                SELECT
                    turn_index,
                    template_name,
                    template_hash,
                    model_alias,
                    raw_output,
                    compiled_prompt,
                    input_payload,
                    created_at
                FROM context_summaries
                WHERE session_id = ? AND vault_name = ?
                ORDER BY id DESC
                """,
                (session_id, vault_name),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    turn_index,
                    template_name,
                    template_hash,
                    model_alias,
                    raw_output,
                    compiled_prompt,
                    input_payload,
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
        input_payload = None
        try:
            input_payload = json.loads(row[6]) if row[6] else None
        except Exception:
            input_payload = None

        snapshots.append(
            {
                "turn_index": row[0],
                "template_name": row[1],
                "template_hash": row[2],
                "model_alias": row[3],
                "raw_output": row[4],
                "compiled_prompt": row[5],
                "input_payload": input_payload,
                "created_at": row[7],
            }
        )

    return snapshots
