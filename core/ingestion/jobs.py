"""
Persistence for ingestion jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import JSON, DateTime, Integer, String, Table, Text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from core.database import (
    Base,
    create_engine_from_system_db,
    create_session_factory,
    create_tables,
)
from core.ingestion.models import JobStatus


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_uri: Mapped[str] = mapped_column(String, nullable=False)
    vault: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    mime_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=JobStatus.QUEUED.value
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    outputs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


def _get_engine() -> Engine:
    # Uses the centralized declared system DB registry.
    return create_engine_from_system_db("ingestion_jobs")


def _get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(_get_engine())


def init_db() -> None:
    """Create tables if they do not exist."""
    engine = _get_engine()
    create_tables(engine, cast(Table, IngestionJob.__table__))


def create_job(
    source_uri: str,
    vault: str,
    source_type: str,
    mime_hint: str | None,
    options: dict[str, Any] | None,
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


def update_job_status(job_id: int, status: JobStatus, error: str | None = None) -> None:
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


def get_job(job_id: int) -> IngestionJob | None:
    session_factory = _get_session_factory()
    with session_factory() as session:
        return cast(IngestionJob | None, session.get(IngestionJob, job_id))


def find_job_for_source(
    source_uri: str, vault: str, statuses: list[str] | None = None
) -> IngestionJob | None:
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
        return cast(IngestionJob | None, query.first())


def list_jobs(limit: int = 50) -> list[IngestionJob]:
    session_factory = _get_session_factory()
    with session_factory() as session:
        return cast(
            list[IngestionJob],
            session.query(IngestionJob)
            .order_by(IngestionJob.created_at.desc())
            .limit(limit)
            .all(),
        )
