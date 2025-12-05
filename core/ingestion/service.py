"""
Ingestion service wired into runtime.
"""

from __future__ import annotations

from typing import List
from pathlib import Path

from core.constants import ASSISTANTMD_ROOT_DIR, IMPORT_DIR
from core.ingestion.segmenter import default_segmenter
from core.ingestion.renderers import default_renderer
from core.ingestion.storage import default_storage
from core.ingestion.models import (
    JobStatus,
    RenderOptions,
    RenderMode,
)
from core.ingestion.sources.pdf import load_pdf_from_path
from core.ingestion.strategies.pdf_text import extract_pdf_text
from core.runtime.paths import get_data_root

from core.ingestion.jobs import (
    create_job,
    init_db,
    list_jobs,
    update_job_status,
    IngestionJob,
    get_job,
    update_job_outputs,
)
from core.logger import UnifiedLogger


class IngestionService:
    def __init__(self):
        self.logger = UnifiedLogger(tag="ingestion")
        init_db()

    def enqueue_job(self, source_uri: str, vault: str, source_type: str, mime_hint: str | None, options: dict | None) -> IngestionJob:
        return create_job(source_uri, vault, source_type, mime_hint, options)

    def list_recent_jobs(self, limit: int = 50) -> List[IngestionJob]:
        return list_jobs(limit)

    def get_job(self, job_id: int) -> IngestionJob | None:
        return get_job(job_id)

    def mark_processing(self, job_id: int):
        update_job_status(job_id, JobStatus.PROCESSING)

    def mark_completed(self, job_id: int):
        update_job_status(job_id, JobStatus.COMPLETED)

    def mark_failed(self, job_id: int, error: str):
        update_job_status(job_id, JobStatus.FAILED, error)

    def process_job(self, job_id: int):
        """
        Process a single ingestion job end-to-end.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Ingestion job {job_id} not found")

        self.mark_processing(job_id)

        try:
            vault = job.vault
            if not vault:
                raise ValueError("Job missing vault")

            data_root = Path(get_data_root())
            import_root = data_root / vault / ASSISTANTMD_ROOT_DIR / IMPORT_DIR
            source_path = Path(job.source_uri)
            if not source_path.is_absolute():
                source_path = import_root / source_path
            if not source_path.exists():
                raise FileNotFoundError(f"Source file not found: {source_path}")

            raw_doc = load_pdf_from_path(source_path)
            extracted = extract_pdf_text(raw_doc)

            relative_dir = ""
            try:
                source_parent = source_path.parent.resolve()
                import_root_resolved = import_root.resolve()
                if str(source_parent).startswith(str(import_root_resolved)):
                    relative_dir = str(source_parent.relative_to(import_root_resolved)).strip("/")
                    if relative_dir:
                        relative_dir = relative_dir + "/"
            except Exception:
                relative_dir = ""

            render_options = RenderOptions(
                mode=RenderMode.FULL,
                store_original=False,
                title=raw_doc.suggested_title,
                vault=vault,
                source_filename=str(source_path),
                relative_dir=relative_dir,
            )
            chunks = default_segmenter(extracted, render_options)
            rendered = default_renderer(extracted, chunks, render_options)
            outputs = default_storage(rendered, render_options)

            update_job_outputs(job_id, outputs)
            self.mark_completed(job_id)
        except Exception as exc:
            self.mark_failed(job_id, str(exc))
            raise
