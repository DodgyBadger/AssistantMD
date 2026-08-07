"""API orchestration for ingestion jobs."""

from pathlib import Path
from typing import Any

from core.constants import ASSISTANTMD_ROOT_DIR, IMPORT_DIR
from core.identity import ExecutionAuthority, require_current_execution_authority
from core.ingestion.jobs import IngestionJob, find_job_for_source
from core.ingestion.models import JobStatus, SourceKind
from core.ingestion.registry import importer_registry
from core.ingestion.service import IngestionService
from core.ingestion.task_execution import process_ingestion_job_in_task
from core.runtime.context import RuntimeContext
from core.runtime.execution_tasks import ExecutionTaskSource
from core.runtime.state import get_runtime_context

from .shared import logger


async def scan_import_folder(
    vault: str,
    queue_only: bool = False,
    strategies: list[str] | None = None,
    capture_ocr_images: bool | None = None,
    pdf_mode: str | None = None,
) -> tuple[list[IngestionJob], list[str]]:
    """Enqueue supported import-folder files and optionally process them."""
    runtime, ingest_service, jobs_created, skipped = _enqueue_import_scan_jobs(
        vault=vault,
        strategies=strategies,
        capture_ocr_images=capture_ocr_images,
        pdf_mode=pdf_mode,
    )

    if not queue_only and jobs_created:
        refreshed_jobs: list[IngestionJob] = []
        for job in jobs_created:
            await _process_ingestion_job_for_api(
                runtime,
                ingest_service,
                job.id,
                vault,
                authority=require_current_execution_authority(),
            )
            refreshed_jobs.append(ingest_service.get_job(job.id) or job)
        jobs_created = refreshed_jobs

    logger.info(
        "Import scan completed",
        data={
            "vault": vault,
            "jobs_created": len(jobs_created),
            "skipped": len(skipped),
            "queue_only": queue_only,
        },
    )
    return jobs_created, skipped


def _enqueue_import_scan_jobs(
    *,
    vault: str,
    strategies: list[str] | None,
    capture_ocr_images: bool | None,
    pdf_mode: str | None,
) -> tuple[RuntimeContext, IngestionService, list[IngestionJob], list[str]]:
    """Create ingestion jobs for supported files in a vault import folder."""
    runtime = get_runtime_context()
    import_root = (
        Path(runtime.config.data_root) / vault / ASSISTANTMD_ROOT_DIR / IMPORT_DIR
    )
    legacy_import_root = (
        Path(runtime.config.data_root) / vault / ASSISTANTMD_ROOT_DIR / "import"
    )
    import_root.mkdir(parents=True, exist_ok=True)

    ingest_service = runtime.ingestion
    jobs_created: list[IngestionJob] = []
    skipped: list[str] = []
    supported_exts = {key for key in importer_registry.keys() if key.startswith(".")}

    search_roots = [import_root]
    if legacy_import_root.exists():
        search_roots.append(legacy_import_root)

    extractor_options: dict[str, Any] = {}
    if capture_ocr_images is not None:
        extractor_options["ocr_capture_images"] = bool(capture_ocr_images)
    normalized_pdf_mode = (pdf_mode or "").strip().lower()
    if normalized_pdf_mode not in {"", "markdown", "page_images"}:
        normalized_pdf_mode = ""

    for root in search_roots:
        for item in sorted(root.iterdir()):
            if item.is_dir():
                continue
            if item.suffix.lower() not in supported_exts:
                skipped.append(item.name)
                continue
            existing_job = find_job_for_source(
                source_uri=item.name,
                vault=vault,
                statuses=[JobStatus.QUEUED.value, JobStatus.PROCESSING.value],
            )
            if existing_job:
                skipped.append(item.name)
                continue

            job_options: dict[str, Any] = {}
            if strategies:
                job_options["strategies"] = strategies
            if extractor_options:
                job_options["extractor_options"] = extractor_options
            if normalized_pdf_mode:
                job_options["pdf_mode"] = normalized_pdf_mode

            jobs_created.append(
                ingest_service.enqueue_job(
                    source_uri=item.name,
                    vault=vault,
                    source_type=SourceKind.FILE.value,
                    mime_hint=None,
                    options=job_options,
                )
            )

    return runtime, ingest_service, jobs_created, skipped


async def import_url_direct(
    vault: str,
    url: str,
    clean_html: bool = True,
) -> IngestionJob:
    """Import one URL immediately as API-attributed ingestion."""
    runtime = get_runtime_context()
    ingest_service = runtime.ingestion
    job = ingest_service.enqueue_job(
        source_uri=url,
        vault=vault,
        source_type=SourceKind.URL.value,
        mime_hint="text/html",
        options={"extractor_options": {"clean_html": clean_html}},
    )
    await _process_ingestion_job_for_api(
        runtime,
        ingest_service,
        job.id,
        vault,
        authority=require_current_execution_authority(),
    )
    refreshed_job = ingest_service.get_job(job.id) or job
    outputs = refreshed_job.outputs
    logger.info(
        "Import URL completed",
        data={
            "vault": vault,
            "status": refreshed_job.status,
            "outputs_count": len(outputs) if outputs is not None else 0,
            "clean_html": clean_html,
        },
    )
    return refreshed_job


async def _process_ingestion_job_for_api(
    runtime: RuntimeContext,
    ingest_service: IngestionService,
    job_id: int,
    vault: str,
    *,
    authority: ExecutionAuthority,
) -> None:
    """Process one API-triggered ingestion job under execution task context."""
    try:
        await process_ingestion_job_in_task(
            task_coordinator=runtime.task_coordinator,
            process_job_fn=ingest_service.process_job,
            job_id=job_id,
            vault=vault,
            source=ExecutionTaskSource.API,
            authority=authority,
        )
    except Exception:
        # process_job persists status/error; callers inspect the refreshed job.
        pass
