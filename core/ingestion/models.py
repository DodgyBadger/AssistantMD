from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceKind(str, Enum):
    FILE = "file"
    URL = "url"
    API = "api"
    MAIL = "mail"


class RenderMode(str, Enum):
    FULL = "full"
    CHUNKED = "chunked"
    SUMMARY_ONLY = "summary_only"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RawDocument:
    source_uri: str
    kind: SourceKind
    mime: Optional[str]
    payload: bytes | str
    suggested_title: Optional[str] = None
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedDocument:
    plain_text: str
    mime: Optional[str]
    strategy_id: str
    blocks: Optional[List[Dict[str, Any]]] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    id: str
    order: int
    text: str
    title: Optional[str] = None
    parent_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    hash: Optional[str] = None


@dataclass
class RenderOptions:
    mode: RenderMode = RenderMode.FULL
    path_pattern: str = "Imported/"
    max_tokens_per_chunk: int = 0  # 0 = no limit
    overlap: int = 0
    store_original: bool = False
    title: Optional[str] = None
    vault: Optional[str] = None
    source_filename: Optional[str] = None
    relative_dir: str = ""
