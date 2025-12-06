"""
Basic URL importer for web-based sources.
"""

from __future__ import annotations

from typing import Optional

import requests

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.registry import importer_registry


_DEFAULT_TIMEOUT = 10
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB guardrail
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) AssistantMD-Ingestion/1.0 Safari/537.36"
}


def _read_limited_content(resp: requests.Response, max_bytes: int) -> bytes:
    """
    Read response content up to max_bytes to avoid unbounded memory use.
    """
    total = 0
    chunks: list[bytes] = []
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError(f"Response exceeded {max_bytes} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


def load_url(source_uri: str, *, timeout: Optional[int] = None, max_bytes: int = _MAX_BYTES) -> RawDocument:
    """
    Fetch a single URL and return a RawDocument.
    """
    to = timeout or _DEFAULT_TIMEOUT
    resp = requests.get(source_uri, timeout=to, stream=True, headers=_DEFAULT_HEADERS)
    resp.raise_for_status()
    body = _read_limited_content(resp, max_bytes)

    content_type = resp.headers.get("content-type", "") or ""
    mime = content_type.split(";")[0].strip() or None

    text: str
    try:
        text = body.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        text = body.decode("utf-8", errors="replace")

    return RawDocument(
        source_uri=source_uri,
        kind=SourceKind.URL,
        mime=mime or "text/html",
        payload=text,
        suggested_title=source_uri,
        meta={"status": resp.status_code, "headers": dict(resp.headers)},
    )


# Register importer for URLs
importer_registry.register("url", load_url)
importer_registry.register("scheme:http", load_url)
importer_registry.register("scheme:https", load_url)
