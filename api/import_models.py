from __future__ import annotations

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
    status: str
    error: str | None = None
    outputs: list[str] | None = None


class ImportScanResponse(BaseModel):
    jobs_created: list[ImportJobInfo]
    skipped: list[str]


class ImportUrlRequest(BaseModel):
    vault: str
    url: str
    clean_html: bool = True


class ImportUrlResponse(BaseModel):
    id: int
    source_uri: str
    vault: str
    status: str
    error: str | None = None
    outputs: list[str] | None = None
