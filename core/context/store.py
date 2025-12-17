from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any

from core.context.templates import TemplateRecord
from core.database import get_system_database_path
from core.logger import UnifiedLogger

logger = UnifiedLogger(tag="context-store")


DB_NAME = "context_manager"


def _get_db_path(system_root: Optional[Path] = None) -> str:
    return get_system_database_path(DB_NAME, str(system_root) if system_root else None)


def _ensure_db(system_root: Optional[Path] = None) -> str:
    """Create database file and tables if missing."""
    db_path = _get_db_path(system_root)
    conn = sqlite3.connect(db_path)
    try:
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
                input_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                "created_at": row[8],
            }
        )

    return snapshots


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
            SELECT summary_json, raw_output, compiled_prompt, input_payload
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
    }
