"""
Job-specific database operations for APScheduler SQLAlchemy job store.

Simple utilities for setting up the SQLAlchemy job store.
"""

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from core.database import get_system_database_path


def create_job_store(system_root: str = None) -> SQLAlchemyJobStore:
    """Create APScheduler SQLAlchemy job store for persistent job storage.

    Args:
        system_root: Optional override for system data directory
    Returns:
        Configured SQLAlchemyJobStore instance
    """
    database_path = get_system_database_path("scheduler_jobs", system_root)
    database_url = f"sqlite:///{database_path}"

    return SQLAlchemyJobStore(url=database_url)
