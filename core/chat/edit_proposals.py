"""Chat-owned collaborative vault file edit proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.chat.schema import DB_NAME, ensure_chat_sessions_schema
from core.constants import (
    EDIT_PROPOSAL_REVIEW_APPLIED_SECTION,
    EDIT_PROPOSAL_REVIEW_ARTIFACT_LABEL,
    EDIT_PROPOSAL_REVIEW_COMMENT_LABEL,
    EDIT_PROPOSAL_REVIEW_DENIED_MARKER,
    EDIT_PROPOSAL_REVIEW_DISPLAY_PREFIX,
    EDIT_PROPOSAL_REVIEW_PROMPT_PREAMBLE,
    EDIT_PROPOSAL_REVIEW_UNRESOLVED_SECTION,
)
from core.database import connect_sqlite_from_system_db
from core.logger import UnifiedLogger
from core.utils.hash import hash_file_bytes, hash_file_content
from core.vault_state.file_operations import (
    PreparedCreateFile,
    PreparedDeleteFile,
    PreparedMoveFile,
    PreparedTextMutation,
    TextReplacement,
    VaultFileOperationRejected,
    prepare_create_file,
    prepare_delete_file,
    prepare_move_file,
    prepare_text_replacements_once,
    write_prepared_create_file,
    write_prepared_delete_file,
    write_prepared_move_file,
    write_prepared_text_mutation,
)
from core.vault_state.pathing import normalize_vault_relative_path, resolve_vault_relative_path


logger = UnifiedLogger(tag="edit-proposals")
MAX_PROPOSAL_EDITS = 20
REPLACE_TEXT_OPERATION = "replace_text"
CREATE_FILE_OPERATION = "create_file"
DELETE_FILE_OPERATION = "delete_file"
MOVE_FILE_OPERATION = "move_file"
SUPPORTED_EDIT_OPERATIONS = {
    REPLACE_TEXT_OPERATION,
    CREATE_FILE_OPERATION,
    DELETE_FILE_OPERATION,
    MOVE_FILE_OPERATION,
}


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
    operation: str
    path: str
    rationale: str
    original_text: str
    replacement_text: str
    before_sha256: str
    destination: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "edit_id": self.edit_id,
            "operation": self.operation,
            "path": self.path,
            "rationale": self.rationale,
            "original_text": self.original_text,
            "replacement_text": self.replacement_text,
            "before_sha256": self.before_sha256,
            "destination": self.destination,
        }


def build_edit_proposal_review_prompts(
    *,
    proposal: dict[str, Any],
    review_decisions: list[dict[str, Any]],
    applied_decisions: list[dict[str, Any]],
) -> tuple[str, str]:
    """Build server-owned model and display prompts for edit proposal review."""
    edits_by_id = {
        str(edit.get("edit_id") or ""): edit
        for edit in proposal.get("edits", [])
        if str(edit.get("edit_id") or "")
    }
    artifact_ref = str(proposal.get("artifact_ref") or "")
    model_lines = [
        EDIT_PROPOSAL_REVIEW_PROMPT_PREAMBLE,
        "",
        f"{EDIT_PROPOSAL_REVIEW_ARTIFACT_LABEL}: `{artifact_ref}`",
        "",
    ]
    display_lines = [
        f"{EDIT_PROPOSAL_REVIEW_DISPLAY_PREFIX} from artifact `{artifact_ref}`.",
        "",
    ]
    if applied_decisions:
        model_lines.append(EDIT_PROPOSAL_REVIEW_APPLIED_SECTION)
        display_lines.append(EDIT_PROPOSAL_REVIEW_APPLIED_SECTION)
        for decision in applied_decisions:
            edit = edits_by_id.get(str(decision.get("edit_id") or ""), {})
            line = f"- Edit `{decision.get('edit_id') or ''}` in @{edit.get('path') or ''}"
            model_lines.append(line)
            display_lines.append(line)
        model_lines.append("")
        display_lines.append("")

    model_lines.extend([EDIT_PROPOSAL_REVIEW_UNRESOLVED_SECTION, ""])
    display_lines.extend([EDIT_PROPOSAL_REVIEW_UNRESOLVED_SECTION, ""])
    for decision in review_decisions:
        edit_id = str(decision.get("edit_id") or "")
        edit = edits_by_id.get(edit_id, {})
        decision_label = _review_decision_label(str(decision.get("decision") or ""))
        line = f"- Edit `{edit_id}` in @{edit.get('path') or ''}: {decision_label}"
        model_lines.append(line)
        display_lines.append(line)
        comment = str(decision.get("comment") or "").strip()
        if comment:
            comment_line = f"  {EDIT_PROPOSAL_REVIEW_COMMENT_LABEL}: {comment}"
            model_lines.append(comment_line)
            display_lines.append(comment_line)
        if str(decision.get("decision") or "") == "deny":
            model_lines.append(f"  {EDIT_PROPOSAL_REVIEW_DENIED_MARKER}")

    return "\n".join(model_lines), "\n".join(display_lines)


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
    prepared_mutations: list[
        PreparedTextMutation | PreparedCreateFile | PreparedDeleteFile | PreparedMoveFile
    ] = []
    replace_edits = [
        edit for edit in edits
        if _edit_operation(edit) == REPLACE_TEXT_OPERATION
    ]
    for path, path_edits in _group_edits_by_path(replace_edits).items():
        expected_hash = str(path_edits[0].get("before_sha256") or "")
        replacements: list[TextReplacement] = []
        for edit in path_edits:
            edit_id = str(edit.get("edit_id") or "")
            original = str(edit.get("original_text") or "")
            replacement = str(overrides.get(edit_id, edit.get("replacement_text") or ""))
            replacements.append(
                TextReplacement(
                    edit_id=edit_id,
                    original_text=original,
                    replacement_text=replacement,
                )
            )
        try:
            prepared = prepare_text_replacements_once(
                vault_path=vault_root,
                path=path,
                replacements=replacements,
                expected_sha256=expected_hash,
                markdown_only=False,
            )
        except VaultFileOperationRejected as exc:
            details = dict(exc.details)
            if exc.code == "file_not_found":
                raise EditProposalError(
                    "VaultFileNotFound",
                    f"Vault file not found: {path}",
                    details={"path": path, **details},
                ) from exc
            if exc.code == "file_conflict":
                raise EditProposalError(
                    "VaultFileConflict",
                    f"File changed since proposal was created: {path}",
                    details={
                        "path": path,
                        "expected_sha256": details.get("expected_sha256"),
                        "actual_sha256": details.get("actual_sha256"),
                    },
                ) from exc
            if exc.code == "invalid_edit":
                edit_id = str(details.get("edit_id") or "")
                raise EditProposalError(
                    "InvalidEdit",
                    f"Edit {edit_id} has empty original text.",
                    details={"path": path, **details},
                ) from exc
            if exc.code == "text_match_count_mismatch":
                raise EditProposalError(
                    "EditTextMismatch",
                    f"Original text no longer matches exactly once in {path}.",
                    details={"path": path, **details},
                ) from exc
            raise EditProposalError(
                exc.code,
                str(exc),
                details={"path": path, **details},
            ) from exc
        prepared_mutations.append(prepared)

    for edit in edits:
        operation = _edit_operation(edit)
        if operation == REPLACE_TEXT_OPERATION:
            continue
        edit_id = str(edit.get("edit_id") or "")
        path = str(edit.get("path") or "")
        expected_hash = str(edit.get("before_sha256") or "")
        try:
            if operation == CREATE_FILE_OPERATION:
                prepared_mutations.append(
                    prepare_create_file(
                        vault_path=vault_root,
                        path=path,
                        content=str(overrides.get(edit_id, edit.get("replacement_text") or "")),
                        markdown_only=False,
                    )
                )
            elif operation == DELETE_FILE_OPERATION:
                prepared_mutations.append(
                    prepare_delete_file(
                        vault_path=vault_root,
                        path=path,
                        expected_sha256=expected_hash,
                        markdown_only=False,
                    )
                )
            elif operation == MOVE_FILE_OPERATION:
                destination = str(overrides.get(edit_id, edit.get("destination") or ""))
                prepared_mutations.append(
                    prepare_move_file(
                        vault_path=vault_root,
                        path=path,
                        destination=destination,
                        expected_sha256=expected_hash,
                        markdown_only=False,
                    )
                )
        except VaultFileOperationRejected as exc:
            _raise_operation_error(
                exc=exc,
                path=path,
                edit_id=edit_id,
                operation=operation,
            )

    applied_paths: list[str] = []
    for prepared in prepared_mutations:
        if isinstance(prepared, PreparedTextMutation):
            result = write_prepared_text_mutation(
                vault_path=vault_root,
                prepared=prepared,
                operation="apply_edit_proposal",
                markdown_only=False,
            )
            applied_paths.append(result.path)
        elif isinstance(prepared, PreparedCreateFile):
            result = write_prepared_create_file(
                vault_path=vault_root,
                prepared=prepared,
                markdown_only=False,
            )
            applied_paths.append(result.path)
        elif isinstance(prepared, PreparedDeleteFile):
            result = write_prepared_delete_file(
                vault_path=vault_root,
                prepared=prepared,
                markdown_only=False,
            )
            applied_paths.append(result.path)
        elif isinstance(prepared, PreparedMoveFile):
            source_result, destination_result = write_prepared_move_file(
                vault_path=vault_root,
                prepared=prepared,
                markdown_only=False,
            )
            applied_paths.extend([source_result.path, destination_result.path])

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
    operation = _edit_operation(raw_edit)
    if operation not in SUPPORTED_EDIT_OPERATIONS:
        raise EditProposalError(
            "InvalidOperation",
            f"Edit {index} has unsupported operation '{operation}'.",
            details={"operation": operation, "supported_operations": sorted(SUPPORTED_EDIT_OPERATIONS)},
        )
    path = normalize_vault_relative_path(str(raw_edit.get("path") or ""))
    if not path:
        raise EditProposalError("InvalidPath", f"Edit {index} is missing a vault file path.")
    full_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=path,
        markdown_only=False,
    )
    if operation == CREATE_FILE_OPERATION:
        if full_path.exists():
            raise EditProposalError(
                "VaultFileExists",
                f"Vault file already exists: {path}",
                details={"path": path},
            )
        content = _replacement_text_from_raw(raw_edit)
        return PreparedEdit(
            edit_id=str(raw_edit.get("edit_id") or f"edit-{index}"),
            operation=operation,
            path=path,
            rationale=str(raw_edit.get("rationale") or "").strip(),
            original_text="",
            replacement_text=content,
            before_sha256="",
        )

    if not full_path.is_file():
        raise EditProposalError(
            "VaultFileNotFound",
            f"Vault file not found: {path}",
            details={"path": path},
        )

    if operation == DELETE_FILE_OPERATION:
        return PreparedEdit(
            edit_id=str(raw_edit.get("edit_id") or f"edit-{index}"),
            operation=operation,
            path=path,
            rationale=str(raw_edit.get("rationale") or "").strip(),
            original_text=str(raw_edit.get("original_text") or ""),
            replacement_text="",
            before_sha256=hash_file_bytes(full_path, length=None),
        )

    if operation == MOVE_FILE_OPERATION:
        destination = normalize_vault_relative_path(str(raw_edit.get("destination") or ""))
        if not destination:
            raise EditProposalError(
                "InvalidDestination",
                f"Edit {index} is missing a destination path.",
                details={"path": path},
            )
        destination_path = resolve_vault_relative_path(
            vault_path=vault_root,
            path=destination,
            markdown_only=False,
        )
        if destination_path.exists():
            raise EditProposalError(
                "VaultDestinationExists",
                f"Vault destination already exists: {destination}",
                details={"path": path, "destination": destination},
            )
        return PreparedEdit(
            edit_id=str(raw_edit.get("edit_id") or f"edit-{index}"),
            operation=operation,
            path=path,
            rationale=str(raw_edit.get("rationale") or "").strip(),
            original_text=str(raw_edit.get("original_text") or ""),
            replacement_text=destination,
            before_sha256=hash_file_bytes(full_path, length=None),
            destination=destination,
        )

    content = full_path.read_text(encoding="utf-8")
    original = str(raw_edit.get("original_text") or "")
    replacement = _replacement_text_from_raw(raw_edit)
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
        operation=operation,
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


def _edit_operation(edit: dict[str, Any]) -> str:
    return str(edit.get("operation") or REPLACE_TEXT_OPERATION).strip() or REPLACE_TEXT_OPERATION


def _replacement_text_from_raw(edit: dict[str, Any]) -> str:
    return str(
        edit.get("replacement_text")
        or edit.get("content")
        or edit.get("initial_content")
        or ""
    )


def _raise_operation_error(
    *,
    exc: VaultFileOperationRejected,
    path: str,
    edit_id: str,
    operation: str,
) -> None:
    details = dict(exc.details)
    if exc.code == "file_not_found":
        raise EditProposalError(
            "VaultFileNotFound",
            f"Vault file not found: {path}",
            details={"path": path, "edit_id": edit_id, "operation": operation, **details},
        ) from exc
    if exc.code == "file_exists":
        raise EditProposalError(
            "VaultFileExists",
            f"Vault file already exists: {path}",
            details={"path": path, "edit_id": edit_id, "operation": operation, **details},
        ) from exc
    if exc.code == "destination_exists":
        raise EditProposalError(
            "VaultDestinationExists",
            f"Vault destination already exists: {details.get('destination') or ''}",
            details={"path": path, "edit_id": edit_id, "operation": operation, **details},
        ) from exc
    if exc.code == "invalid_destination":
        raise EditProposalError(
            "InvalidDestination",
            "Move destination is required.",
            details={"path": path, "edit_id": edit_id, "operation": operation, **details},
        ) from exc
    if exc.code == "file_conflict":
        raise EditProposalError(
            "VaultFileConflict",
            f"File changed since proposal was created: {path}",
            details={
                "path": path,
                "edit_id": edit_id,
                "operation": operation,
                "expected_sha256": details.get("expected_sha256"),
                "actual_sha256": details.get("actual_sha256"),
            },
        ) from exc
    raise EditProposalError(
        exc.code,
        str(exc),
        details={"path": path, "edit_id": edit_id, "operation": operation, **details},
    ) from exc


def _review_decision_label(decision: str) -> str:
    if decision == "approve":
        return "Approved"
    if decision == "comment":
        return "Comment"
    if decision == "deny":
        return "Denied"
    return "Pending"


def _sha256_text(content: str) -> str:
    return hash_file_content(content, length=None)
