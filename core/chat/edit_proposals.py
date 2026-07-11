"""Read-only access to historical inline edit proposals."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from core.chat.schema import DB_NAME, ensure_chat_sessions_schema
from core.database import connect_sqlite_from_system_db


class EditProposalError(ValueError):
    """Raised when a historical edit proposal cannot be read."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def get_edit_proposal(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
) -> dict[str, Any]:
    """Return a stored proposal for historical chat rendering."""
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT proposal_json, status, created_at, applied_at
            FROM chat_edit_proposals
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (artifact_ref, session_id, vault_name),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise EditProposalError(
            "EditProposalNotFound",
            "Edit proposal was not found for this chat session.",
            details={"artifact_ref": artifact_ref},
        )

    try:
        proposal = json.loads(row["proposal_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise EditProposalError(
            "InvalidStoredProposal",
            "Stored edit proposal is invalid.",
        ) from exc
    if not isinstance(proposal, dict):
        raise EditProposalError(
            "InvalidStoredProposal",
            "Stored edit proposal has invalid shape.",
        )

    proposal["status"] = row["status"]
    proposal["created_at"] = row["created_at"]
    proposal["applied_at"] = row["applied_at"]
    return proposal
