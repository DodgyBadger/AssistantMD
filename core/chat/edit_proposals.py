"""Chat-owned collaborative vault file edit proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.chat.schema import DB_NAME, ensure_chat_sessions_schema
from core.database import connect_sqlite_from_system_db
from core.logger import UnifiedLogger
from core.vault_state.file_mutations import replace_vault_file_content
from core.vault_state.pathing import normalize_vault_relative_path, resolve_vault_relative_path


logger = UnifiedLogger(tag="edit-proposals")
MAX_PROPOSAL_EDITS = 20


class EditProposalError(ValueError):
    """Raised when an edit proposal cannot be created or applied."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PreparedEdit:
    """One validated proposal edit."""

    edit_id: str
    path: str
    rationale: str
    original_text: str
    replacement_text: str
    before_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "edit_id": self.edit_id,
            "path": self.path,
            "rationale": self.rationale,
            "original_text": self.original_text,
            "replacement_text": self.replacement_text,
            "before_sha256": self.before_sha256,
        }


def create_edit_proposal(
    *,
    vault_name: str,
    vault_path: str | Path,
    session_id: str,
    edits: list[dict[str, Any]],
    title: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """Validate and store a chat edit-proposal artifact."""
    if not session_id:
        raise EditProposalError("MissingSession", "Edit proposals require an active chat session.")
    if not edits:
        raise EditProposalError("NoEdits", "Edit proposal must include at least one edit.")
    if len(edits) > MAX_PROPOSAL_EDITS:
        raise EditProposalError(
            "TooManyEdits",
            f"Edit proposal can include at most {MAX_PROPOSAL_EDITS} edits.",
        )

    vault_root = Path(vault_path).resolve()
    prepared = [
        _prepare_edit(vault_root=vault_root, raw_edit=raw_edit, index=index)
        for index, raw_edit in enumerate(edits, start=1)
    ]
    artifact_ref = f"edit-proposals/{uuid4().hex}"
    proposal = {
        "artifact_ref": artifact_ref,
        "artifact_kind": "file_edit_proposal",
        "vault_name": vault_name,
        "session_id": session_id,
        "title": title.strip() or "Proposed file edits",
        "summary": summary.strip(),
        "status": "pending",
        "edits": [edit.to_dict() for edit in prepared],
    }
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO chat_edit_proposals (
                artifact_ref, session_id, vault_name, status, proposal_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                artifact_ref,
                session_id,
                vault_name,
                "pending",
                json.dumps(proposal, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    logger.add_sink("validation").info(
        "edit_proposal_created",
        data={
            "event": "edit_proposal_created",
            "vault_name": vault_name,
            "session_id": session_id,
            "artifact_ref": artifact_ref,
            "edit_count": len(prepared),
        },
    )
    return proposal


def get_edit_proposal(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
) -> dict[str, Any]:
    """Return a stored edit proposal artifact."""
    row = _fetch_proposal_row(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
    )
    proposal = _loads_proposal(row["proposal_json"])
    proposal["status"] = row["status"]
    proposal["created_at"] = row["created_at"]
    proposal["applied_at"] = row["applied_at"]
    return proposal


def apply_edit_proposal(
    *,
    vault_name: str,
    vault_path: str | Path,
    session_id: str,
    artifact_ref: str,
    selected_edit_ids: list[str],
    replacement_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply selected edit proposal operations after hash and text checks."""
    row = _fetch_proposal_row(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
    )
    if row["status"] == "applied":
        raise EditProposalError(
            "ProposalAlreadyApplied",
            "This edit proposal has already been applied.",
        )
    if row["status"] == "denied":
        raise EditProposalError(
            "ProposalDenied",
            "This edit proposal has been denied.",
        )
    selected = {str(item).strip() for item in selected_edit_ids if str(item).strip()}
    if not selected:
        raise EditProposalError("NoSelectedEdits", "Select at least one edit to apply.")
    overrides = replacement_overrides or {}
    proposal = _loads_proposal(row["proposal_json"])
    edits = [
        edit for edit in proposal.get("edits", [])
        if str(edit.get("edit_id") or "") in selected
    ]
    if len(edits) != len(selected):
        raise EditProposalError(
            "UnknownEdit",
            "One or more selected edits are not part of this proposal.",
        )

    vault_root = Path(vault_path).resolve()
    updated_content_by_path: dict[str, str] = {}
    for path, path_edits in _group_edits_by_path(edits).items():
        full_path = resolve_vault_relative_path(
            vault_path=vault_root,
            path=path,
            markdown_only=False,
        )
        if not full_path.is_file():
            raise EditProposalError(
                "VaultFileNotFound",
                f"Vault file not found: {path}",
                details={"path": path},
            )
        current = full_path.read_text(encoding="utf-8")
        expected_hash = str(path_edits[0].get("before_sha256") or "")
        current_hash = _sha256_text(current)
        if expected_hash and current_hash != expected_hash:
            raise EditProposalError(
                "VaultFileConflict",
                f"File changed since proposal was created: {path}",
                details={"path": path, "expected_sha256": expected_hash, "actual_sha256": current_hash},
            )
        updated = current
        for edit in path_edits:
            edit_id = str(edit.get("edit_id") or "")
            original = str(edit.get("original_text") or "")
            replacement = str(overrides.get(edit_id, edit.get("replacement_text") or ""))
            if not original:
                raise EditProposalError("InvalidEdit", f"Edit {edit_id} has empty original text.")
            if updated.count(original) != 1:
                raise EditProposalError(
                    "EditTextMismatch",
                    f"Original text no longer matches exactly once in {path}.",
                    details={"path": path, "edit_id": edit_id},
                )
            updated = updated.replace(original, replacement, 1)
        updated_content_by_path[path] = updated

    applied_paths: list[str] = []
    for path, content in updated_content_by_path.items():
        replace_vault_file_content(
            vault_path=vault_root,
            path=path,
            content=content,
            operation="apply_edit_proposal",
            markdown_only=False,
        )
        applied_paths.append(path)

    applied_at = datetime.now(UTC).isoformat()
    proposal["status"] = "applied"
    proposal["applied_at"] = applied_at
    proposal["applied_edit_ids"] = sorted(selected)
    conn = connect_sqlite_from_system_db(DB_NAME)
    try:
        conn.execute(
            """
            UPDATE chat_edit_proposals
            SET status = 'applied', applied_at = ?, proposal_json = ?
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (
                applied_at,
                json.dumps(proposal, ensure_ascii=False, sort_keys=True),
                artifact_ref,
                session_id,
                vault_name,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.add_sink("validation").info(
        "edit_proposal_applied",
        data={
            "event": "edit_proposal_applied",
            "vault_name": vault_name,
            "session_id": session_id,
            "artifact_ref": artifact_ref,
            "edit_count": len(edits),
            "paths": applied_paths,
        },
    )
    return {
        "artifact_ref": artifact_ref,
        "status": "applied",
        "applied_edit_ids": sorted(selected),
        "applied_paths": applied_paths,
        "applied_at": applied_at,
    }


def deny_edit_proposal(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
) -> dict[str, Any]:
    """Mark an edit proposal as denied without writing files."""
    row = _fetch_proposal_row(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
    )
    if row["status"] == "applied":
        raise EditProposalError(
            "ProposalAlreadyApplied",
            "This edit proposal has already been applied.",
        )
    proposal = _loads_proposal(row["proposal_json"])
    denied_at = datetime.now(UTC).isoformat()
    proposal["status"] = "denied"
    proposal["denied_at"] = denied_at
    conn = connect_sqlite_from_system_db(DB_NAME)
    try:
        conn.execute(
            """
            UPDATE chat_edit_proposals
            SET status = 'denied', proposal_json = ?
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (
                json.dumps(proposal, ensure_ascii=False, sort_keys=True),
                artifact_ref,
                session_id,
                vault_name,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.add_sink("validation").info(
        "edit_proposal_denied",
        data={
            "event": "edit_proposal_denied",
            "vault_name": vault_name,
            "session_id": session_id,
            "artifact_ref": artifact_ref,
        },
    )
    return {
        "artifact_ref": artifact_ref,
        "status": "denied",
        "denied_at": denied_at,
    }


def _prepare_edit(*, vault_root: Path, raw_edit: dict[str, Any], index: int) -> PreparedEdit:
    path = normalize_vault_relative_path(str(raw_edit.get("path") or ""))
    if not path:
        raise EditProposalError("InvalidPath", f"Edit {index} is missing a vault file path.")
    full_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=path,
        markdown_only=False,
    )
    if not full_path.is_file():
        raise EditProposalError(
            "VaultFileNotFound",
            f"Vault file not found: {path}",
            details={"path": path},
        )
    content = full_path.read_text(encoding="utf-8")
    original = str(raw_edit.get("original_text") or "")
    replacement = str(raw_edit.get("replacement_text") or "")
    if not original:
        raise EditProposalError("InvalidEdit", f"Edit {index} is missing original_text.")
    if content.count(original) != 1:
        raise EditProposalError(
            "EditTextMismatch",
            f"original_text for {path} must match exactly once.",
            details={"path": path, "match_count": content.count(original)},
        )
    return PreparedEdit(
        edit_id=str(raw_edit.get("edit_id") or f"edit-{index}"),
        path=path,
        rationale=str(raw_edit.get("rationale") or "").strip(),
        original_text=original,
        replacement_text=replacement,
        before_sha256=_sha256_text(content),
    )


def _fetch_proposal_row(*, vault_name: str, session_id: str, artifact_ref: str) -> dict[str, Any]:
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = lambda cursor, row: {
        column[0]: row[index] for index, column in enumerate(cursor.description)
    }
    try:
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, status, proposal_json, created_at, applied_at
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
            "Edit proposal artifact was not found for this chat session.",
            details={"artifact_ref": artifact_ref},
        )
    return row


def _loads_proposal(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise EditProposalError("InvalidStoredProposal", "Stored edit proposal is invalid.") from exc
    if not isinstance(loaded, dict):
        raise EditProposalError("InvalidStoredProposal", "Stored edit proposal has invalid shape.")
    return loaded


def _group_edits_by_path(edits: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edit in edits:
        path = normalize_vault_relative_path(str(edit.get("path") or ""))
        grouped.setdefault(path, []).append(edit)
    return grouped


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
