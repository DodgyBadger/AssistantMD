"""
Basic URL importer for web-based sources.
"""

from __future__ import annotations

from typing import Optional
import re

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.registry import importer_registry
from core.ingestion.sources.url_fetchers import fetch_url_with_curl


_DEFAULT_READ_TIMEOUT = 10
_DEFAULT_CONNECT_TIMEOUT = 10
_DEFAULT_FETCH_BACKEND = "curl"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB guardrail
_DEFAULT_HEADERS: dict[str, str] = {}


def load_url(
    source_uri: str,
    *,
    timeout: Optional[int] = None,
    connect_timeout: Optional[int] = None,
    backend: Optional[str] = None,
    max_bytes: int = _MAX_BYTES,
) -> RawDocument:
    """
    Fetch a single URL and return a RawDocument.
    """
    read_timeout = max(1, int(timeout or _DEFAULT_READ_TIMEOUT))
    connect_timeout_s = max(1, int(connect_timeout or _DEFAULT_CONNECT_TIMEOUT))
    selected_backend = (backend or _DEFAULT_FETCH_BACKEND).strip().lower()

    if selected_backend != "curl":
        raise RuntimeError(f"Unsupported URL fetch backend: {selected_backend}")

    fetched = fetch_url_with_curl(
        source_uri,
        connect_timeout_seconds=connect_timeout_s,
        read_timeout_seconds=read_timeout,
        max_bytes=max_bytes,
        headers=_DEFAULT_HEADERS,
    )

    if fetched.status_code in (401, 403, 429):
        raise RuntimeError(
            f"Access blocked ({fetched.status_code}). Some sites require a browser/session; save as PDF or paste content manually."
        )
    if fetched.status_code >= 400:
        raise RuntimeError(f"URL fetch failed with status {fetched.status_code}: {source_uri}")

    content_type = fetched.headers.get("content-type", "") or ""
    mime = content_type.split(";")[0].strip() or None

    text: str
    try:
        text = fetched.body.decode("utf-8", errors="replace")
    except Exception:
        text = fetched.body.decode("utf-8", errors="replace")

    title = _extract_title(text) or source_uri

    return RawDocument(
        source_uri=source_uri,
        kind=SourceKind.URL,
        mime=mime or "text/html",
        payload=text,
        suggested_title=title,
        meta={
            "status": fetched.status_code,
            "headers": dict(fetched.headers),
            "effective_url": fetched.effective_url,
            "remote_ip": fetched.remote_ip,
            "time_total_seconds": fetched.time_total_seconds,
        },
    )


# Register importer for URLs
importer_registry.register("url", load_url)
importer_registry.register("scheme:http", load_url)
importer_registry.register("scheme:https", load_url)


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _extract_title(html: str) -> str | None:
    """
    Extract the contents of the <title> element from HTML.
    """
    match = _TITLE_RE.search(html)
    if not match:
        return None
    title = match.group(1)
    # Collapse whitespace
    cleaned = " ".join(title.split()).strip()
    return cleaned or None
