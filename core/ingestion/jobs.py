"""
Persistence for ingestion jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON
from sqlalchemy.exc import SQLAlchemyError

from core.database import Base, create_engine_from_system_db, create_session_factory
from core.ingestion.models import JobStatus


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_uri = Column(String, nullable=False)
    vault = Column(String, nullable=True)
    source_type = Column(String, nullable=False)
    mime_hint = Column(String, nullable=True)
    options = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default=JobStatus.QUEUED.value)
    error = Column(Text, nullable=True)
    outputs = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


def _get_engine():
    return create_engine_from_system_db("ingestion_jobs")


def _get_session_factory():
    return create_session_factory(_get_engine())


def init_db() -> None:
    """Create tables if they do not exist."""
    engine = _get_engine()
    Base.metadata.create_all(engine, tables=[IngestionJob.__table__])


def create_job(
    source_uri: str,
    vault: str,
    source_type: str,
    mime_hint: Optional[str],
    options: Optional[dict],
) -> IngestionJob:
    session_factory = _get_session_factory()
    try:
        with session_factory() as session:
            job = IngestionJob(
                source_uri=source_uri,
                vault=vault,
                source_type=source_type,
                mime_hint=mime_hint,
                options=options or {},
                status=JobStatus.QUEUED.value,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Failed to create ingestion job: {exc}") from exc


def update_job_status(job_id: int, status: JobStatus, error: Optional[str] = None) -> None:
    session_factory = _get_session_factory()
    try:
        with session_factory() as session:
            job: IngestionJob | None = session.get(IngestionJob, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")

            job.status = status.value
            if error:
                job.error = error
            session.commit()
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Failed to update job {job_id}: {exc}") from exc


def update_job_outputs(job_id: int, outputs: list[str]) -> None:
    session_factory = _get_session_factory()
    try:
        with session_factory() as session:
            job: IngestionJob | None = session.get(IngestionJob, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")

            job.outputs = outputs
            session.commit()
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Failed to update outputs for job {job_id}: {exc}") from exc


def get_job(job_id: int) -> Optional[IngestionJob]:
    session_factory = _get_session_factory()
    with session_factory() as session:
        return session.get(IngestionJob, job_id)


def find_job_for_source(source_uri: str, vault: str, statuses: Optional[list[str]] = None) -> Optional[IngestionJob]:
    """
    Find the most recent job for a source/vault matching optional statuses.
    """
    session_factory = _get_session_factory()
    with session_factory() as session:
        query = (
            session.query(IngestionJob)
            .filter(IngestionJob.source_uri == source_uri, IngestionJob.vault == vault)
            .order_by(IngestionJob.created_at.desc())
        )
        if statuses:
            query = query.filter(IngestionJob.status.in_(statuses))
        return query.first()


def list_jobs(limit: int = 50) -> list[IngestionJob]:
    session_factory = _get_session_factory()
    with session_factory() as session:
        return (
            session.query(IngestionJob)
            .order_by(IngestionJob.created_at.desc())
            .limit(limit)
            .all()
        )
