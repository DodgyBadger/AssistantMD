from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ImportScanRequest(BaseModel):
    vault: str
    queue_only: bool = False
    strategies: list[str] | None = None  # Optional per-run strategy override
    capture_ocr_images: bool | None = (
        None  # Optional per-run OCR image capture override
    )
    pdf_mode: str | None = (
        None  # Optional per-run PDF mode override: markdown|page_images
    )


class ImportJobInfo(BaseModel):
    id: int
    source_uri: str
    vault: str
    source_type: str
    status: str
    error: str | None = None
    outputs: list[str] | None = None
    created_at: datetime
    updated_at: datetime


class ImportJobListResponse(BaseModel):
    jobs: list[ImportJobInfo]
    next_cursor: str | None = None
    total_matching: int
    status_counts: dict[str, int]


class ImportJobCancelResponse(BaseModel):
    job: ImportJobInfo
    cancelled: bool


class ImportRunNowResponse(BaseModel):
    accepted: bool
    queued_count: int
    triggered_at: datetime


class ImportScanResponse(BaseModel):
    jobs_created: list[ImportJobInfo]
    skipped: list[str]


class ImportUrlRequest(BaseModel):
    vault: str
    url: str
    clean_html: bool = True
    strategies: list[str] | None = None
    capture_ocr_images: bool | None = None
    pdf_mode: str | None = None


class ImportUrlResponse(ImportJobInfo):
    pass
