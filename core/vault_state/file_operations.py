"""Unified vault file operation helpers.

This layer owns operation-level validation and text mutation behavior. Final
write/delete/move recording still belongs to ``core.vault_state.file_mutations``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.constants import VIRTUAL_MOUNTS
from core.utils.hash import hash_file_bytes, hash_file_content
from core.vault_state.file_mutations import (
    RecordedMutationResult,
    delete_vault_file,
    move_vault_file,
    replace_vault_file_content,
    write_vault_file,
)
from core.vault_state.pathing import normalize_vault_relative_path, resolve_vault_relative_path


class VaultFileOperationRejected(Exception):
    """Raised when a vault file operation fails before or during mutation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class VaultTextTarget:
    """Resolved vault text-file target."""

    requested_path: str
    path: str
    full_path: Path

    @property
    def requested_path_metadata(self) -> dict[str, str]:
        if self.requested_path and self.requested_path != self.path:
            return {"requested_path": self.requested_path}
        return {}


@dataclass(frozen=True)
class TextReplacement:
    """One exact text replacement request."""

    original_text: str
    replacement_text: str
    edit_id: str | None = None


@dataclass(frozen=True)
class TextMutationResult:
    """Result of a text mutation operation."""

    path: str
    requested_path: str
    replacement_count: int
    mutation: RecordedMutationResult

    @property
    def requested_path_metadata(self) -> dict[str, str]:
        if self.requested_path and self.requested_path != self.path:
            return {"requested_path": self.requested_path}
        return {}


@dataclass(frozen=True)
class PreparedTextMutation:
    """Validated text mutation content ready to write."""

    path: str
    requested_path: str
    content: str
    replacement_count: int

    @property
    def requested_path_metadata(self) -> dict[str, str]:
        if self.requested_path and self.requested_path != self.path:
            return {"requested_path": self.requested_path}
        return {}


@dataclass(frozen=True)
class PreparedCreateFile:
    """Validated create-file operation ready to write."""

    path: str
    content: str


@dataclass(frozen=True)
class PreparedDeleteFile:
    """Validated delete-file operation ready to write."""

    path: str


@dataclass(frozen=True)
class PreparedMoveFile:
    """Validated move-file operation ready to write."""

    path: str
    destination: str


def resolve_text_target(
    *,
    vault_path: str | Path,
    path: str,
    markdown_only: bool,
    prefer_markdown_extension: bool = False,
) -> VaultTextTarget:
    """Resolve a vault-relative text target with optional markdown-first lookup."""
    requested_path = normalize_vault_relative_path(path)
    _reject_virtual_mount_path(requested_path)
    vault_root = Path(vault_path).resolve()

    if prefer_markdown_extension and _should_try_markdown_file(requested_path):
        markdown_path = f"{requested_path}.md"
        markdown_full_path = resolve_vault_relative_path(
            vault_path=vault_root,
            path=markdown_path,
            markdown_only=markdown_only,
        )
        if markdown_full_path.is_file():
            return VaultTextTarget(
                requested_path=requested_path,
                path=markdown_path,
                full_path=markdown_full_path,
            )

    full_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=requested_path,
        markdown_only=markdown_only,
    )
    return VaultTextTarget(
        requested_path=requested_path,
        path=requested_path,
        full_path=full_path,
    )


def resolve_markdown_text_target(*, vault_path: str | Path, path: str) -> VaultTextTarget:
    """Resolve a markdown text mutation target with extensionless .md preference."""
    return resolve_text_target(
        vault_path=vault_path,
        path=path,
        markdown_only=True,
        prefer_markdown_extension=True,
    )


def replace_text(
    *,
    vault_path: str | Path,
    path: str,
    old_text: str,
    new_text: str,
    count: int,
    operation: str,
    markdown_only: bool = True,
    prefer_markdown_extension: bool = False,
    expected_sha256: str | None = None,
    require_match_count: int | None = None,
) -> TextMutationResult:
    """Replace text in one vault file after operation-level validation."""
    target = resolve_text_target(
        vault_path=vault_path,
        path=path,
        markdown_only=markdown_only,
        prefer_markdown_extension=prefer_markdown_extension,
    )
    current = _read_existing_text_file(target)
    if count < 1:
        raise VaultFileOperationRejected(
            "invalid_count",
            f"Invalid count {count} - must be >= 1",
            details={"count": count, "path": target.path, **target.requested_path_metadata},
        )
    _check_expected_sha256(target=target, current=current, expected_sha256=expected_sha256)

    match_count = current.count(old_text)
    if match_count == 0:
        raise VaultFileOperationRejected(
            "text_not_found",
            f"Text not found in '{target.path}': '{old_text}'",
            details={"path": target.path, **target.requested_path_metadata},
        )
    if require_match_count is not None and match_count != require_match_count:
        raise VaultFileOperationRejected(
            "text_match_count_mismatch",
            f"Text must match exactly {require_match_count} time(s) in {target.path}.",
            details={
                "path": target.path,
                "match_count": match_count,
                "required_match_count": require_match_count,
                **target.requested_path_metadata,
            },
        )

    replacement_count = min(match_count, count)
    mutation = replace_vault_file_content(
        vault_path=vault_path,
        path=target.path,
        content=current.replace(old_text, new_text, count),
        operation=operation,
        markdown_only=markdown_only,
    )
    return TextMutationResult(
        path=target.path,
        requested_path=target.requested_path,
        replacement_count=replacement_count,
        mutation=mutation,
    )


def replace_text_once_with_hash(
    *,
    vault_path: str | Path,
    path: str,
    original_text: str,
    replacement_text: str,
    expected_sha256: str,
    operation: str,
    markdown_only: bool = False,
) -> TextMutationResult:
    """Replace exactly one text occurrence after checking the file content hash."""
    return replace_text(
        vault_path=vault_path,
        path=path,
        old_text=original_text,
        new_text=replacement_text,
        count=1,
        operation=operation,
        markdown_only=markdown_only,
        expected_sha256=expected_sha256,
        require_match_count=1,
    )


def apply_text_replacements_once(
    *,
    vault_path: str | Path,
    path: str,
    replacements: list[TextReplacement],
    expected_sha256: str | None,
    operation: str,
    markdown_only: bool = False,
) -> TextMutationResult:
    """Apply validated exact-once replacements to one file and write it once."""
    prepared = prepare_text_replacements_once(
        vault_path=vault_path,
        path=path,
        replacements=replacements,
        expected_sha256=expected_sha256,
        markdown_only=markdown_only,
    )
    return write_prepared_text_mutation(
        vault_path=vault_path,
        prepared=prepared,
        operation=operation,
        markdown_only=markdown_only,
    )


def prepare_text_replacements_once(
    *,
    vault_path: str | Path,
    path: str,
    replacements: list[TextReplacement],
    expected_sha256: str | None,
    markdown_only: bool = False,
) -> PreparedTextMutation:
    """Validate exact-once replacements and return the resulting full content."""
    target = resolve_text_target(
        vault_path=vault_path,
        path=path,
        markdown_only=markdown_only,
    )
    current = _read_existing_text_file(target)
    _check_expected_sha256(target=target, current=current, expected_sha256=expected_sha256)

    updated = current
    for replacement in replacements:
        if not replacement.original_text:
            raise VaultFileOperationRejected(
                "invalid_edit",
                _edit_message(replacement, "has empty original text."),
                details={"path": target.path, **_edit_details(replacement)},
            )
        match_count = updated.count(replacement.original_text)
        if match_count != 1:
            raise VaultFileOperationRejected(
                "text_match_count_mismatch",
                f"Original text no longer matches exactly once in {target.path}.",
                details={
                    "path": target.path,
                    "match_count": match_count,
                    **_edit_details(replacement),
                },
            )
        updated = updated.replace(
            replacement.original_text,
            replacement.replacement_text,
            1,
        )

    return PreparedTextMutation(
        path=target.path,
        requested_path=target.requested_path,
        content=updated,
        replacement_count=len(replacements),
    )


def write_prepared_text_mutation(
    *,
    vault_path: str | Path,
    prepared: PreparedTextMutation,
    operation: str,
    markdown_only: bool = False,
) -> TextMutationResult:
    """Write a prepared text mutation through the recorded mutation path."""
    mutation = replace_vault_file_content(
        vault_path=vault_path,
        path=prepared.path,
        content=prepared.content,
        operation=operation,
        markdown_only=markdown_only,
    )
    return TextMutationResult(
        path=prepared.path,
        requested_path=prepared.requested_path,
        replacement_count=prepared.replacement_count,
        mutation=mutation,
    )


def replace_full_text_content(
    *,
    vault_path: str | Path,
    path: str,
    content: str,
    operation: str,
    expected_sha256: str | None = None,
    markdown_only: bool = False,
) -> TextMutationResult:
    """Replace a full text file after an optional current-content hash check."""
    target = resolve_text_target(
        vault_path=vault_path,
        path=path,
        markdown_only=markdown_only,
    )
    current = _read_existing_text_file(target)
    _check_expected_sha256(target=target, current=current, expected_sha256=expected_sha256)
    mutation = replace_vault_file_content(
        vault_path=vault_path,
        path=target.path,
        content=content,
        operation=operation,
        markdown_only=markdown_only,
    )
    return TextMutationResult(
        path=target.path,
        requested_path=target.requested_path,
        replacement_count=1,
        mutation=mutation,
    )


def prepare_create_file(
    *,
    vault_path: str | Path,
    path: str,
    content: str,
    markdown_only: bool = False,
) -> PreparedCreateFile:
    """Validate a create-file operation without writing."""
    target = resolve_text_target(
        vault_path=vault_path,
        path=path,
        markdown_only=markdown_only,
    )
    if target.full_path.exists():
        raise VaultFileOperationRejected(
            "file_exists",
            f"Vault file already exists: {target.path}",
            details={"path": target.path, **target.requested_path_metadata},
        )
    return PreparedCreateFile(path=target.path, content=content)


def write_prepared_create_file(
    *,
    vault_path: str | Path,
    prepared: PreparedCreateFile,
    markdown_only: bool = False,
) -> RecordedMutationResult:
    """Write a prepared create-file operation through the recorded mutation path."""
    return write_vault_file(
        vault_path=vault_path,
        path=prepared.path,
        content=prepared.content,
        fail_if_exists=True,
        markdown_only=markdown_only,
    )


def prepare_delete_file(
    *,
    vault_path: str | Path,
    path: str,
    expected_sha256: str | None,
    markdown_only: bool = False,
) -> PreparedDeleteFile:
    """Validate a delete-file operation without writing."""
    target = resolve_text_target(
        vault_path=vault_path,
        path=path,
        markdown_only=markdown_only,
    )
    _check_existing_file_hash(target=target, expected_sha256=expected_sha256)
    return PreparedDeleteFile(path=target.path)


def write_prepared_delete_file(
    *,
    vault_path: str | Path,
    prepared: PreparedDeleteFile,
    markdown_only: bool = False,
) -> RecordedMutationResult:
    """Write a prepared delete-file operation through the recorded mutation path."""
    return delete_vault_file(
        vault_path=vault_path,
        path=prepared.path,
        markdown_only=markdown_only,
    )


def prepare_move_file(
    *,
    vault_path: str | Path,
    path: str,
    destination: str,
    expected_sha256: str | None,
    markdown_only: bool = False,
) -> PreparedMoveFile:
    """Validate a move-file operation without writing."""
    normalized_destination = normalize_vault_relative_path(destination)
    if not normalized_destination:
        raise VaultFileOperationRejected(
            "invalid_destination",
            "Move destination is required.",
            details={"path": normalize_vault_relative_path(path)},
        )
    source = resolve_text_target(
        vault_path=vault_path,
        path=path,
        markdown_only=markdown_only,
    )
    destination_target = resolve_text_target(
        vault_path=vault_path,
        path=normalized_destination,
        markdown_only=markdown_only,
    )
    _check_existing_file_hash(target=source, expected_sha256=expected_sha256)
    if destination_target.full_path.exists():
        raise VaultFileOperationRejected(
            "destination_exists",
            f"Vault destination already exists: {destination_target.path}",
            details={
                "path": source.path,
                "destination": destination_target.path,
                **source.requested_path_metadata,
            },
        )
    return PreparedMoveFile(path=source.path, destination=destination_target.path)


def write_prepared_move_file(
    *,
    vault_path: str | Path,
    prepared: PreparedMoveFile,
    markdown_only: bool = False,
) -> tuple[RecordedMutationResult, RecordedMutationResult]:
    """Write a prepared move-file operation through the recorded mutation path."""
    return move_vault_file(
        vault_path=vault_path,
        path=prepared.path,
        destination=prepared.destination,
        overwrite=False,
        markdown_only=markdown_only,
    )


def _read_existing_text_file(target: VaultTextTarget) -> str:
    if not target.full_path.exists():
        raise VaultFileOperationRejected(
            "file_not_found",
            f"Vault file not found: {target.path}",
            details={"path": target.path, **target.requested_path_metadata},
        )
    if not target.full_path.is_file():
        raise VaultFileOperationRejected(
            "not_file",
            f"Vault path is not a file: {target.path}",
            details={"path": target.path, **target.requested_path_metadata},
        )
    try:
        return target.full_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise VaultFileOperationRejected(
            "file_not_text",
            f"Vault file is not UTF-8 text: {target.path}",
            details={"path": target.path, **target.requested_path_metadata},
        ) from exc


def _check_existing_file_hash(
    *,
    target: VaultTextTarget,
    expected_sha256: str | None,
) -> None:
    if not target.full_path.exists():
        raise VaultFileOperationRejected(
            "file_not_found",
            f"Vault file not found: {target.path}",
            details={"path": target.path, **target.requested_path_metadata},
        )
    if not target.full_path.is_file():
        raise VaultFileOperationRejected(
            "not_file",
            f"Vault path is not a file: {target.path}",
            details={"path": target.path, **target.requested_path_metadata},
        )
    if not expected_sha256:
        return
    current_sha256 = _sha256_file(target.full_path)
    if expected_sha256 != current_sha256:
        raise VaultFileOperationRejected(
            "file_conflict",
            f"File changed since expected hash was captured: {target.path}",
            details={
                "path": target.path,
                "expected_sha256": expected_sha256,
                "actual_sha256": current_sha256,
                **target.requested_path_metadata,
            },
        )


def _check_expected_sha256(
    *,
    target: VaultTextTarget,
    current: str,
    expected_sha256: str | None,
) -> None:
    if not expected_sha256:
        return
    current_sha256 = _sha256_text(current)
    if expected_sha256 != current_sha256:
        raise VaultFileOperationRejected(
            "file_conflict",
            f"File changed since expected hash was captured: {target.path}",
            details={
                "path": target.path,
                "expected_sha256": expected_sha256,
                "actual_sha256": current_sha256,
                **target.requested_path_metadata,
            },
        )


def _sha256_text(content: str) -> str:
    return hash_file_content(content, length=None)


def _sha256_file(path: Path) -> str:
    return hash_file_bytes(path, length=None)


def _reject_virtual_mount_path(path: str) -> None:
    if not path:
        return
    mount_key = path.strip().lstrip("./").split("/", 1)[0]
    if mount_key in VIRTUAL_MOUNTS:
        raise ValueError(f"'{mount_key}' is reserved for a virtual mount")


def _should_try_markdown_file(path: str) -> bool:
    if not path or path in {".", "/"} or path.endswith("/"):
        return False
    return "." not in Path(path).name


def _edit_details(replacement: TextReplacement) -> dict[str, str]:
    if replacement.edit_id:
        return {"edit_id": replacement.edit_id}
    return {}


def _edit_message(replacement: TextReplacement, suffix: str) -> str:
    if replacement.edit_id:
        return f"Edit {replacement.edit_id} {suffix}"
    return f"Edit {suffix}"
