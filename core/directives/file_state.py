"""
File processing state management for {pending} patterns.

Tracks which files have been processed by workflows to support incremental processing.
"""

import hashlib
import os
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy import Column, String, DateTime

from core.database import Base, create_engine_from_system_db, create_session_factory
from core.runtime.paths import get_data_root
from core.logger import UnifiedLogger

logger = UnifiedLogger(tag="file-state")


def hash_file_content(content: str) -> str:
    """Create a hash of file content for unique identification.

    Uses SHA256 hash of file content. This approach:
    - Is path-independent (files can be moved/renamed)
    - Detects content changes (will re-process if file is edited)
    - Avoids path format issues (relative vs absolute, with/without extensions)

    Args:
        content: File content to hash

    Returns:
        First 16 characters of SHA256 hash (sufficient for uniqueness)
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


class ProcessedFile(Base):
    """Model for tracking processed files across all vaults.

    Uses content hashing for robust file identification across renames/moves.
    Stores both hash (for comparison) and filepath (for debugging).
    """
    __tablename__ = "processed_files"

    vault_name = Column(String, primary_key=True, nullable=False)
    workflow_id = Column("assistant_id", String, primary_key=True, nullable=False)
    pattern = Column(String, primary_key=True, nullable=False)
    # SHA256 hash for comparison
    content_hash = Column(String, primary_key=True, nullable=False)
    filepath = Column(String, nullable=False)  # Human-readable path for debugging
    processed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkflowFileStateManager:
    """Manages persistent state for workflow file processing.

    Uses a single system database to track which files have been
    processed by each workflow for each @input-file pattern across all vaults.
    """

    def __init__(self, vault_name: str, workflow_id: str):
        """Initialize state manager for a specific vault and workflow.

        Args:
            vault_name: Name of the vault (not full path)
            workflow_id: Workflow identifier (typically vault/name format)
        """
        self.vault_name = vault_name
        self.workflow_id = workflow_id
        self.vault_path = os.path.join(str(get_data_root()), vault_name)

        # Create SQLAlchemy engine and session factory for file_state database
        self.engine = create_engine_from_system_db("file_state")
        self.SessionFactory = create_session_factory(self.engine)

        self._init_database()
    
    def _init_database(self):
        """Initialize database schema if it doesn't exist."""
        Base.metadata.create_all(self.engine)
    
    def _normalize_path_for_state(self, filepath: str) -> str:
        """
        Normalize file path to vault-relative, extension-stripped form used for
        state tracking.
        """
        if not os.path.isabs(filepath):
            abs_path = os.path.join(self.vault_path, filepath)
        else:
            abs_path = filepath

        relative_path = os.path.relpath(abs_path, self.vault_path)
        if relative_path.endswith('.md'):
            relative_path = relative_path[:-3]
        return relative_path.replace('\\', '/')

    def get_processed_state(self, pattern: str) -> Tuple[Set[str], Dict[str, datetime]]:
        """Get processed hashes and per-path processed timestamps for a pattern."""
        with self.SessionFactory() as session:
            results = session.query(
                ProcessedFile.content_hash,
                ProcessedFile.filepath,
                ProcessedFile.processed_at
            ).filter(
                ProcessedFile.vault_name == self.vault_name,
                ProcessedFile.workflow_id == self.workflow_id,
                ProcessedFile.pattern == pattern
            ).all()

            hashes = set()
            path_processed_at: Dict[str, datetime] = {}

            for content_hash, filepath, processed_at in results:
                hashes.add(content_hash)
                normalized_path = self._normalize_path_for_state(filepath)
                existing = path_processed_at.get(normalized_path)
                if not existing or processed_at > existing:
                    path_processed_at[normalized_path] = processed_at

            return hashes, path_processed_at

    def get_processed_files(self, pattern: str) -> Set[str]:
        """Backward-compatible helper returning only processed hashes."""
        hashes, _ = self.get_processed_state(pattern)
        return hashes
    
    def mark_files_processed(self, file_records: List[dict], pattern: str):
        """Mark files as processed for a specific pattern.

        Args:
            file_records: List of dicts with 'content_hash' and 'filepath' keys
            pattern: The @input-file pattern (e.g., "journal/{pending:5}")
        """
        if not file_records:
            return

        with self.SessionFactory() as session:
            for record in file_records:
                # Use merge for INSERT OR REPLACE behavior
                processed_file = ProcessedFile(
                    vault_name=self.vault_name,
                    workflow_id=self.workflow_id,
                    pattern=pattern,
                    content_hash=record['content_hash'],
                    filepath=self._normalize_path_for_state(record['filepath']),
                    processed_at=datetime.utcnow()
                )
                session.merge(processed_file)

            session.commit()
    
    def get_pending_files(
        self,
        all_files: List[str],
        pattern: str,
        count_limit: Optional[int] = None
    ) -> List[str]:
        """Filter list of files to return only pending (unprocessed) files.

        Returns files in chronological order (oldest first) up to the count limit.
        Core function that implements {pending} variable behavior.

        Uses content hashing for file identification - files are matched by content
        hash rather than path, making this robust to file renames/moves and
        avoiding path format issues.

        Args:
            all_files: List of all available file paths (absolute paths, should be
                pre-sorted chronologically)
            pattern: The @input-file pattern that requested these files
            count_limit: Maximum number of files to return

        Returns:
            List of file paths for unprocessed files, preserving chronological order
        """
        processed_hashes, path_processed_at = self.get_processed_state(pattern)

        # Filter out processed files - compare by content hash
        pending_files = []
        for filepath in all_files:
            normalized_path = self._normalize_path_for_state(filepath)
            try:
                # Read file content and hash it
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                file_hash = hash_file_content(content)

                if file_hash in processed_hashes:
                    continue

                # Hybrid check: if path was processed and file hasn't been
                # modified since, treat as processed
                processed_at = path_processed_at.get(normalized_path)
                if processed_at:
                    file_mtime = datetime.utcfromtimestamp(os.path.getmtime(filepath))
                    if file_mtime <= processed_at:
                        continue

                pending_files.append(filepath)
            except (IOError, OSError) as e:
                # If we can't read the file, include it as pending (it will fail
                # later with a clear error)
                logger.warning(
                    f"Warning: Could not read file for hash comparison: {filepath}",
                    data={"error": str(e)},
                )
                pending_files.append(filepath)

        # Preserve chronological order from input (no re-sorting needed)
        # Apply count limit if specified
        if count_limit is not None:
            pending_files = pending_files[:count_limit]

        return pending_files
    
    def update_from_processed_step(self, processed_step):
        """Update state for patterns that require tracking from ProcessedStep data.
        
        Args:
            processed_step: ProcessedStep instance containing directive results
        """
        input_file_data = processed_step.get_directive_value('input_file', [])
        if not input_file_data:
            return
        
        # Handle both single directive and multiple directives cases
        if isinstance(input_file_data, list) and input_file_data:
            if isinstance(input_file_data[0], dict):
                # Single directive case: [{file1}, {file2}]
                file_lists = [input_file_data]
            else:
                # Multiple directive case: [[{file1}], [{file2}]]
                file_lists = input_file_data
        else:
            return
        
        # Check each file list for state metadata
        for file_list in file_lists:
            for file_data in file_list:
                if ('_state_metadata' in file_data
                        and file_data['_state_metadata'].get('requires_tracking')):
                    pattern = file_data['_state_metadata']['pattern']
                    file_records = file_data['_state_metadata']['file_records']
                    self.mark_files_processed(file_records, pattern)
