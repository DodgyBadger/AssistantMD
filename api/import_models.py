from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ImportScanRequest(BaseModel):
    vault: str
    queue_only: bool = False
    strategies: Optional[List[str]] = None  # Optional per-run strategy override
    capture_ocr_images: Optional[bool] = None  # Optional per-run OCR image capture override


class ImportJobInfo(BaseModel):
    id: int
    source_uri: str
    vault: str
    status: str
    error: Optional[str] = None
    outputs: Optional[list[str]] = None


class ImportScanResponse(BaseModel):
    jobs_created: List[ImportJobInfo]
    skipped: List[str]


class ImportUrlRequest(BaseModel):
    vault: str
    url: str
    clean_html: bool = True


class ImportUrlResponse(BaseModel):
    id: int
    source_uri: str
    vault: str
    status: str
    error: Optional[str] = None
    outputs: Optional[list[str]] = None
