"""
File processing state management for {pending} patterns.

Tracks which files have been processed by workflows to support incremental processing.
"""

import hashlib
from datetime import datetime
from typing import List, Set, Optional
from sqlalchemy import Column, String, DateTime

from core.database import Base, create_engine_from_system_db, create_session_factory
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
    content_hash = Column(String, primary_key=True, nullable=False)  # SHA256 hash for comparison
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

        # Create SQLAlchemy engine and session factory for file_state database
        self.engine = create_engine_from_system_db("file_state")
        self.SessionFactory = create_session_factory(self.engine)

        self._init_database()
    
    def _init_database(self):
        """Initialize database schema if it doesn't exist."""
        Base.metadata.create_all(self.engine)
    
    def get_processed_files(self, pattern: str) -> Set[str]:
        """Get set of content hashes for files that have been processed for a pattern.

        Args:
            pattern: The @input-file pattern (e.g., "journal/{pending:5}")

        Returns:
            Set of content hashes that have been marked as processed
        """
        with self.SessionFactory() as session:
            results = session.query(ProcessedFile.content_hash).filter(
                ProcessedFile.vault_name == self.vault_name,
                ProcessedFile.workflow_id == self.workflow_id,
                ProcessedFile.pattern == pattern
            ).all()

            return {row.content_hash for row in results}
    
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
                    filepath=record['filepath'],
                    processed_at=datetime.utcnow()
                )
                session.merge(processed_file)

            session.commit()
    
    def get_pending_files(self, all_files: List[str], pattern: str, count_limit: Optional[int] = None) -> List[str]:
        """Filter list of files to return only pending (unprocessed) files.

        Returns files in chronological order (oldest first) up to the count limit.
        Core function that implements {pending} variable behavior.

        Uses content hashing for file identification - files are matched by content hash
        rather than path, making this robust to file renames/moves and avoiding path format issues.

        Args:
            all_files: List of all available file paths (absolute paths, should be pre-sorted chronologically)
            pattern: The @input-file pattern that requested these files
            count_limit: Maximum number of files to return

        Returns:
            List of file paths for unprocessed files, preserving chronological order
        """
        processed_hashes = self.get_processed_files(pattern)

        # Filter out processed files - compare by content hash
        pending_files = []
        for filepath in all_files:
            try:
                # Read file content and hash it
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                file_hash = hash_file_content(content)

                if file_hash not in processed_hashes:
                    pending_files.append(filepath)
            except (IOError, OSError) as e:
                # If we can't read the file, include it as pending (it will fail later with a clear error)
                logger.activity(
                    f"Warning: Could not read file for hash comparison: {filepath}",
                    level="warning",
                    metadata={"error": str(e)}
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
                if '_state_metadata' in file_data and file_data['_state_metadata'].get('requires_tracking'):
                    pattern = file_data['_state_metadata']['pattern']
                    file_records = file_data['_state_metadata']['file_records']
                    self.mark_files_processed(file_records, pattern)
