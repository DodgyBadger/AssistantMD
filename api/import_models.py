from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ImportScanRequest(BaseModel):
    vault: str
    force: bool = False
    extensions: Optional[List[str]] = None  # e.g., [".pdf"]


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
