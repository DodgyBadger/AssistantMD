"""Normalized web capability models shared by tools and ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WebFetchResult:
    """One bounded HTTP response and its transport provenance."""

    source_url: str
    effective_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    remote_ip: str | None = None
    duration_seconds: float | None = None
    redirect_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebSearchItem:
    """One provider-neutral search result."""

    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class WebSearchResult:
    """Normalized search response."""

    strategy: str
    query: str
    items: list[WebSearchItem]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebExtractionItem:
    """Extracted content for one URL."""

    source_url: str
    effective_url: str
    content: str
    title: str | None = None
    mime: str | None = None
    images: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebItemFailure:
    """One failed URL inside a potentially partial provider response."""

    source_url: str
    error: str
    error_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebExtractionResult:
    """Normalized single- or multi-URL extraction response."""

    strategy: str
    items: list[WebExtractionItem]
    failures: list[WebItemFailure] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebCrawlResult:
    """Normalized website crawl response."""

    strategy: str
    base_url: str
    pages: list[WebExtractionItem]
    failures: list[WebItemFailure] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
