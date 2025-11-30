"""
Simple SQLAlchemy utilities for the AssistantMD.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from core.logger import UnifiedLogger
from core.runtime.paths import get_system_root
from core.runtime.state import get_runtime_context, has_runtime_context

logger = UnifiedLogger(tag="database")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


def get_system_database_path(db_name: str, system_root: str = None) -> str:
    """Get the full path for a system database file.

    Args:
        db_name: Name of the database file (without .db extension)
        system_root: Optional override for system data directory

    Returns:
        Full path to the database file in the system directory
    """
    if system_root is None:
        system_root = str(get_system_root())

    os.makedirs(system_root, exist_ok=True)
    return os.path.join(system_root, f"{db_name}.db")


def create_engine_from_system_db(db_name: str):
    """Create SQLAlchemy engine for a system database with runtime context support.

    Automatically uses the system_root from runtime context when available,
    enabling proper isolation for validation scenarios. Falls back to environment
    variable or default constant when runtime context is not available.

    Args:
        db_name: Name of the database file (without .db extension)

    Returns:
        SQLAlchemy engine
    """
    # Check if runtime context is available (validation or production)
    if has_runtime_context():
        runtime = get_runtime_context()
        system_root = str(runtime.config.system_root)
        database_path = get_system_database_path(db_name, system_root)
    else:
        # Fallback for code running outside runtime context
        database_path = get_system_database_path(db_name)

    database_url = f"sqlite:///{database_path}"
    return create_engine(database_url)


def create_session_factory(engine):
    """Create SQLAlchemy session factory for an engine.

    Args:
        engine: SQLAlchemy engine instance

    Returns:
        SQLAlchemy sessionmaker class
    """
    return sessionmaker(bind=engine)
