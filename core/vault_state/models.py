"""Database models for vault-state manifests and change events."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from core.database import Base


class VaultRecord(Base):
    """Stable vault identity registry local to vault state."""

    __tablename__ = "vaults"

    vault_id = Column(String, primary_key=True, nullable=False)
    current_name = Column(String, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    missing_since = Column(DateTime(timezone=True), nullable=True)


class VaultFile(Base):
    """Current observed state for one vault file."""

    __tablename__ = "vault_files"

    vault_id = Column(String, primary_key=True, nullable=False)
    path = Column(String, primary_key=True, nullable=False)
    vault_name = Column(String, nullable=False)
    artifact_class = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    mtime_ns = Column(Integer, nullable=False)
    content_hash = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    change_sequence = Column(Integer, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class VaultFileEvent(Base):
    """Monotonic change-feed event for vault artifacts."""

    __tablename__ = "vault_file_events"

    sequence = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    vault_id = Column(String, nullable=False)
    vault_name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    content_hash = Column(String, nullable=True)
    artifact_class = Column(String, nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    metadata_json = Column(Text, nullable=True)


class TaskFileMutation(Base):
    """Task-scoped mutation audit row reserved for later rollback slices."""

    __tablename__ = "task_file_mutations"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    task_id = Column(String, nullable=False)
    task_kind = Column(String, nullable=True)
    task_source = Column(String, nullable=True)
    task_scope = Column(String, nullable=True)
    task_label = Column(String, nullable=True)
    vault_id = Column(String, nullable=False)
    vault_name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    related_path = Column(String, nullable=True)
    operation = Column(String, nullable=False)
    event_sequence = Column(Integer, nullable=True)
    before_exists = Column(Boolean, nullable=False)
    before_hash = Column(String, nullable=True)
    after_exists = Column(Boolean, nullable=False)
    after_hash = Column(String, nullable=True)
    snapshot_ref = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class TaskSnapshot(Base):
    """Task snapshot metadata reserved for later rollback slices."""

    __tablename__ = "task_snapshots"

    task_id = Column(String, primary_key=True, nullable=False)
    vault_id = Column(String, primary_key=True, nullable=False)
    vault_name = Column(String, nullable=False)
    snapshot_root = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
