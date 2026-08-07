"""
Basic URL importer for web-based sources.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from core.ingestion.models import RawDocument, SourceKind
from core.ingestion.registry import importer_registry
from core.web.fetchers import fetch_url_with_curl
from core.web.html import extract_html_title

_DEFAULT_READ_TIMEOUT = 10
_DEFAULT_CONNECT_TIMEOUT = 10
_DEFAULT_FETCH_STRATEGY = "curl"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB guardrail
_DEFAULT_HEADERS: dict[str, str] = {}


def load_url(
    source_uri: str,
    *,
    timeout: int | None = None,
    connect_timeout: int | None = None,
    strategy: str | None = None,
    max_bytes: int = _MAX_BYTES,
) -> RawDocument:
    """
    Fetch a single URL and return a RawDocument.
    """
    read_timeout = max(1, int(timeout or _DEFAULT_READ_TIMEOUT))
    connect_timeout_s = max(1, int(connect_timeout or _DEFAULT_CONNECT_TIMEOUT))
    selected_strategy = (strategy or _DEFAULT_FETCH_STRATEGY).strip().lower()

    if selected_strategy != "curl":
        raise RuntimeError(f"Unsupported URL fetch strategy: {selected_strategy}")

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
        raise RuntimeError(f"URL fetch failed with status {fetched.status_code}")

    mime, evidence = _classify_response(
        body=fetched.body,
        content_type=fetched.headers.get("content-type", ""),
        requested_url=source_uri,
        effective_url=fetched.effective_url,
    )
    title = _suggest_title(
        body=fetched.body,
        mime=mime,
        content_disposition=fetched.headers.get("content-disposition", ""),
        effective_url=fetched.effective_url,
        requested_url=source_uri,
    )

    return RawDocument(
        source_uri=source_uri,
        kind=SourceKind.URL,
        mime=mime,
        payload=fetched.body,
        suggested_title=title,
        meta={
            "status": fetched.status_code,
            "headers": dict(fetched.headers),
            "effective_url": fetched.effective_url,
            "remote_ip": fetched.remote_ip,
            "time_total_seconds": fetched.duration_seconds,
            "redirect_count": fetched.redirect_count,
            "classification_evidence": evidence,
        },
    )


# Register importer for URLs
importer_registry.register("url", load_url)
importer_registry.register("scheme:http", load_url)
importer_registry.register("scheme:https", load_url)


def _extract_title(html: str) -> str | None:
    """Compatibility wrapper for the shared HTML title extractor."""
    return extract_html_title(html)


def _classify_response(
    *,
    body: bytes,
    content_type: str,
    requested_url: str,
    effective_url: str,
) -> tuple[str, str]:
    declared_mime = content_type.split(";", 1)[0].strip().lower()
    if body.lstrip().startswith(b"%PDF"):
        return "application/pdf", "payload_signature"
    if declared_mime == "application/pdf":
        return "application/pdf", "content_type"
    if declared_mime in {"text/html", "application/xhtml+xml"}:
        return "text/html", "content_type"
    if _url_suffix(effective_url or requested_url) == ".pdf":
        return "application/pdf", "url_suffix"
    if declared_mime.startswith("text/") or _looks_like_html(body):
        return "text/html", "text_payload"
    display_mime = declared_mime or "unknown"
    raise RuntimeError(f"Unsupported URL response type: {display_mime}")


def _looks_like_html(body: bytes) -> bool:
    prefix = body[:1024].lstrip().lower()
    return prefix.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def _url_suffix(url: str) -> str:
    return PurePosixPath(unquote(urlsplit(url).path)).suffix.lower()


def _suggest_title(
    *,
    body: bytes,
    mime: str,
    content_disposition: str,
    effective_url: str,
    requested_url: str,
) -> str:
    if mime == "text/html":
        html = body.decode("utf-8", errors="replace")
        html_title = _extract_title(html)
        if html_title:
            return html_title

    disposition_name = _content_disposition_filename(content_disposition)
    if disposition_name:
        return PurePosixPath(disposition_name).stem or disposition_name

    path_name = PurePosixPath(
        unquote(urlsplit(effective_url or requested_url).path)
    ).name
    if path_name:
        return PurePosixPath(path_name).stem or path_name
    return "import"


def _content_disposition_filename(value: str) -> str | None:
    if not value:
        return None
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", value, re.IGNORECASE)
    if not match:
        return None
    return unquote(match.group(1).strip()).strip() or None
