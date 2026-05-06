"""Vault-state manifest refresh and change-feed service."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.constants import ASSISTANTMD_ROOT_DIR, AUTHORING_DIR
from core.authoring.template_discovery import discover_vaults
from core.database import create_engine_from_system_db, create_session_factory, create_tables
from core.logger import UnifiedLogger
from core.settings import (
    get_debug_enabled,
    get_vault_state_enabled,
    get_vault_state_excluded_patterns,
)
from core.utils.hash import hash_file_bytes
from core.vault_state.identity import resolve_or_create_vault_identity
from core.vault_state.models import (
    TaskFileMutation,
    TaskSnapshot,
    VaultFile,
    VaultFileEvent,
    VaultRecord,
)
from core.vault_state.patterns import ExcludedPathMatcher


logger = UnifiedLogger(tag="vault-state")


@dataclass(frozen=True)
class VaultStateRefreshResult:
    """Summary of one vault-state refresh."""

    vault_id: str
    vault_name: str
    files_seen: int
    files_created: int
    files_changed: int
    files_deleted: int
    files_unchanged: int
    files_excluded: int
    latest_sequence: int | None
    changed_paths: tuple[str, ...] = field(default_factory=tuple)
    deleted_paths: tuple[str, ...] = field(default_factory=tuple)


class VaultStateService:
    """Maintain a rebuildable vault manifest and monotonic change feed."""

    def __init__(self) -> None:
        self.engine = create_engine_from_system_db("vault_state")
        self.SessionFactory = create_session_factory(self.engine)
        self._init_database()

    def refresh_vault(
        self,
        vault_path: str | Path,
        *,
        vault_name: str | None = None,
    ) -> VaultStateRefreshResult:
        """Refresh the manifest for one vault path."""
        if not get_vault_state_enabled():
            raise RuntimeError("vault_state_enabled is false")

        root = Path(vault_path).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Vault path is not a directory: {root}")

        resolved_name = vault_name or root.name
        identity = resolve_or_create_vault_identity(root)
        matcher = ExcludedPathMatcher.from_patterns(get_vault_state_excluded_patterns())
        now = datetime.now(UTC)

        logger.add_sink("validation").info(
            "vault_state_refresh_started",
            data={
                "event": "vault_state_refresh_started",
                "vault_id": identity.vault_id,
                "vault_name": resolved_name,
            },
        )

        seen_paths: set[str] = set()
        changed_paths: list[str] = []
        deleted_paths: list[str] = []
        files_created = 0
        files_changed = 0
        files_unchanged = 0
        files_excluded = 0
        latest_sequence: int | None = None

        with self.SessionFactory() as session:
            self._register_vault(
                session,
                vault_id=identity.vault_id,
                vault_name=resolved_name,
                now=now,
            )

            existing_rows = {
                row.path: row
                for row in session.scalars(
                    select(VaultFile).where(VaultFile.vault_id == identity.vault_id)
                )
            }

            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative_path = self._relative_path(root, path)
                if matcher.matches(relative_path):
                    files_excluded += 1
                    continue
                seen_paths.add(relative_path)
                stat = path.stat()
                artifact_class = self._classify(relative_path)
                existing = existing_rows.get(relative_path)
                needs_hash = (
                    existing is None
                    or existing.deleted_at is not None
                    or existing.size != stat.st_size
                    or existing.mtime_ns != stat.st_mtime_ns
                    or existing.artifact_class != artifact_class
                )
                if not needs_hash:
                    existing.last_seen_at = now
                    existing.vault_name = resolved_name
                    files_unchanged += 1
                    continue

                content_hash = hash_file_bytes(path, length=None)
                event_type = self._event_type(existing, content_hash, artifact_class)
                if existing is None:
                    event = self._append_event(
                        session,
                        vault_id=identity.vault_id,
                        vault_name=resolved_name,
                        path=relative_path,
                        event_type=event_type,
                        content_hash=content_hash,
                        artifact_class=artifact_class,
                        now=now,
                        metadata={},
                    )
                    latest_sequence = event.sequence
                    session.flush()
                    row = VaultFile(
                        vault_id=identity.vault_id,
                        vault_name=resolved_name,
                        path=relative_path,
                        artifact_class=artifact_class,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        content_hash=content_hash,
                        kind="file",
                        change_sequence=event.sequence,
                        first_seen_at=now,
                        last_seen_at=now,
                        changed_at=now,
                        deleted_at=None,
                    )
                    session.add(row)
                    files_created += 1
                elif (
                    existing.content_hash != content_hash
                    or existing.deleted_at is not None
                    or existing.artifact_class != artifact_class
                ):
                    was_deleted = existing.deleted_at is not None
                    event = self._append_event(
                        session,
                        vault_id=identity.vault_id,
                        vault_name=resolved_name,
                        path=relative_path,
                        event_type=event_type,
                        content_hash=content_hash,
                        artifact_class=artifact_class,
                        now=now,
                        metadata={"previous_hash": existing.content_hash},
                    )
                    latest_sequence = event.sequence
                    session.flush()
                    existing.vault_name = resolved_name
                    existing.artifact_class = artifact_class
                    existing.size = stat.st_size
                    existing.mtime_ns = stat.st_mtime_ns
                    existing.content_hash = content_hash
                    existing.change_sequence = event.sequence
                    existing.last_seen_at = now
                    existing.changed_at = now
                    existing.deleted_at = None
                    if was_deleted:
                        files_created += 1
                    else:
                        files_changed += 1
                else:
                    existing.vault_name = resolved_name
                    existing.artifact_class = artifact_class
                    existing.size = stat.st_size
                    existing.mtime_ns = stat.st_mtime_ns
                    existing.last_seen_at = now
                    existing.deleted_at = None
                    files_unchanged += 1
                    continue

                changed_paths.append(relative_path)
                self._log_file_event(
                    event_type=event_type,
                    vault_id=identity.vault_id,
                    vault_name=resolved_name,
                    path=relative_path,
                    content_hash=content_hash,
                    artifact_class=artifact_class,
                    sequence=latest_sequence,
                )

            files_deleted = 0
            for relative_path, existing in sorted(existing_rows.items()):
                if relative_path in seen_paths or existing.deleted_at is not None:
                    continue
                event = self._append_event(
                    session,
                    vault_id=identity.vault_id,
                    vault_name=resolved_name,
                    path=relative_path,
                    event_type="deleted",
                    content_hash=existing.content_hash,
                    artifact_class=existing.artifact_class,
                    now=now,
                    metadata={},
                )
                session.flush()
                latest_sequence = event.sequence
                existing.vault_name = resolved_name
                existing.last_seen_at = now
                existing.change_sequence = event.sequence
                existing.deleted_at = now
                files_deleted += 1
                deleted_paths.append(relative_path)
                self._log_file_event(
                    event_type="deleted",
                    vault_id=identity.vault_id,
                    vault_name=resolved_name,
                    path=relative_path,
                    content_hash=existing.content_hash,
                    artifact_class=existing.artifact_class,
                    sequence=event.sequence,
                )

            session.commit()

        result = VaultStateRefreshResult(
            vault_id=identity.vault_id,
            vault_name=resolved_name,
            files_seen=len(seen_paths),
            files_created=files_created,
            files_changed=files_changed,
            files_deleted=files_deleted,
            files_unchanged=files_unchanged,
            files_excluded=files_excluded,
            latest_sequence=latest_sequence,
            changed_paths=tuple(changed_paths),
            deleted_paths=tuple(deleted_paths),
        )
        logger.add_sink("validation").info(
            "vault_state_refresh_completed",
            data={
                "event": "vault_state_refresh_completed",
                "vault_id": result.vault_id,
                "vault_name": result.vault_name,
                "files_seen": result.files_seen,
                "files_created": result.files_created,
                "files_changed": result.files_changed,
                "files_deleted": result.files_deleted,
                "files_unchanged": result.files_unchanged,
                "files_excluded": result.files_excluded,
                "latest_sequence": result.latest_sequence,
            },
        )
        return result

    def changes_since(
        self,
        sequence: int,
        *,
        vault_id: str | None = None,
        limit: int | None = None,
    ) -> list[VaultFileEvent]:
        """Return change-feed events after a sequence cursor."""
        with self.SessionFactory() as session:
            stmt = select(VaultFileEvent).where(VaultFileEvent.sequence > sequence)
            if vault_id:
                stmt = stmt.where(VaultFileEvent.vault_id == vault_id)
            stmt = stmt.order_by(VaultFileEvent.sequence.asc())
            if limit is not None:
                stmt = stmt.limit(limit)
            return list(session.scalars(stmt))

    def refresh_all_vaults(self, data_root: str | Path) -> dict[str, Any]:
        """Refresh all discovered vaults under a data root.

        Individual vault refresh failures are logged and summarized without
        aborting startup or manual workflow reload.
        """
        if not get_vault_state_enabled():
            return {
                "vault_state_enabled": False,
                "vault_state_refreshed": 0,
                "vault_state_failed": 0,
            }

        root = Path(data_root)
        refreshed = 0
        failed = 0
        latest_sequence: int | None = None
        for vault_name in discover_vaults(str(root)):
            vault_path = root / vault_name
            try:
                result = self.refresh_vault(vault_path, vault_name=vault_name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.add_sink("validation").warning(
                    "vault_state_refresh_failed",
                    data={
                        "event": "vault_state_refresh_failed",
                        "vault_name": vault_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                continue
            refreshed += 1
            if result.latest_sequence is not None:
                latest_sequence = result.latest_sequence

        logger.add_sink("validation").info(
            "vault_state_refresh_all_completed",
            data={
                "event": "vault_state_refresh_all_completed",
                "data_root": str(root),
                "vaults_refreshed": refreshed,
                "vaults_failed": failed,
                "latest_sequence": latest_sequence,
            },
        )
        return {
            "vault_state_enabled": True,
            "vault_state_refreshed": refreshed,
            "vault_state_failed": failed,
            "vault_state_latest_sequence": latest_sequence,
        }

    def _init_database(self) -> None:
        create_tables(
            self.engine,
            VaultRecord.__table__,
            VaultFile.__table__,
            VaultFileEvent.__table__,
            TaskFileMutation.__table__,
            TaskSnapshot.__table__,
        )

    @staticmethod
    def _relative_path(root: Path, path: Path) -> str:
        return str(path.relative_to(root)).replace("\\", "/")

    @staticmethod
    def _classify(relative_path: str) -> str:
        if relative_path.startswith(f"{ASSISTANTMD_ROOT_DIR}/{AUTHORING_DIR}/"):
            return "assistant_authoring"
        if relative_path.startswith(f"{ASSISTANTMD_ROOT_DIR}/"):
            return "assistant_generated"
        return "user_content"

    @staticmethod
    def _event_type(
        existing: VaultFile | None,
        content_hash: str,
        artifact_class: str,
    ) -> str:
        if existing is None:
            return "created"
        if existing.deleted_at is not None:
            return "created"
        if existing.artifact_class != artifact_class:
            return "classified"
        if existing.content_hash != content_hash:
            return "changed"
        return "observed"

    @staticmethod
    def _register_vault(session: Any, *, vault_id: str, vault_name: str, now: datetime) -> None:
        record = session.get(VaultRecord, vault_id)
        if record is None:
            session.add(
                VaultRecord(
                    vault_id=vault_id,
                    current_name=vault_name,
                    first_seen_at=now,
                    last_seen_at=now,
                    missing_since=None,
                )
            )
            return
        record.current_name = vault_name
        record.last_seen_at = now
        record.missing_since = None

    @staticmethod
    def _append_event(
        session: Any,
        *,
        vault_id: str,
        vault_name: str,
        path: str,
        event_type: str,
        content_hash: str | None,
        artifact_class: str | None,
        now: datetime,
        metadata: dict[str, Any],
    ) -> VaultFileEvent:
        event = VaultFileEvent(
            vault_id=vault_id,
            vault_name=vault_name,
            path=path,
            event_type=event_type,
            content_hash=content_hash,
            artifact_class=artifact_class,
            observed_at=now,
            metadata_json=json.dumps(metadata, sort_keys=True) if metadata else None,
        )
        session.add(event)
        session.flush()
        return event

    @staticmethod
    def _log_file_event(
        *,
        event_type: str,
        vault_id: str,
        vault_name: str,
        path: str,
        content_hash: str | None,
        artifact_class: str | None,
        sequence: int | None,
    ) -> None:
        event_name = (
            "vault_state_file_deleted" if event_type == "deleted" else "vault_state_file_changed"
        )
        data = {
            "event": event_name,
            "vault_id": vault_id,
            "vault_name": vault_name,
            "path": path,
            "event_type": event_type,
            "content_hash": content_hash,
            "artifact_class": artifact_class,
            "sequence": sequence,
        }
        if get_debug_enabled():
            logger.add_sink("validation").info(event_name, data=data)
        else:
            logger.set_sinks(["validation"]).info(event_name, data=data)
