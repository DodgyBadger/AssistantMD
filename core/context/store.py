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
) -> None:
    """Persist a compiled context summary."""
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
