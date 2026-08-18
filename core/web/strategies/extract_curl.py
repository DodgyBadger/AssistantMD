"""Built-in curl plus HTML-to-Markdown extraction strategy."""

from __future__ import annotations

import asyncio

from core.settings import get_default_api_timeout
from core.web.errors import WebStrategyConfigurationError
from core.web.fetchers import fetch_url_with_curl
from core.web.html import extract_html_title, html_to_markdown
from core.web.models import (
    WebExtractionItem,
    WebExtractionResult,
    WebItemFailure,
)

_TEXT_APPLICATION_MIMES = {
    "application/javascript",
    "application/json",
    "application/ld+json",
    "application/xhtml+xml",
    "application/xml",
}


def _is_readable_text(*, mime: str, body: bytes) -> bool:
    """Return whether a response is suitable for transient text extraction."""
    if body.lstrip().startswith(b"%PDF-"):
        return False
    if mime.startswith("text/") or mime in _TEXT_APPLICATION_MIMES:
        return True
    if mime:
        return False
    return b"\x00" not in body[:4096]


async def extract_with_curl(
    *,
    urls: list[str],
    include_images: bool,
) -> WebExtractionResult:
    """Fetch and convert URLs sequentially to keep resource use bounded."""
    if include_images:
        raise WebStrategyConfigurationError(
            "The curl extraction strategy does not provide image metadata"
        )
    items: list[WebExtractionItem] = []
    failures: list[WebItemFailure] = []
    timeout_seconds = max(1, int(get_default_api_timeout()))
    for url in urls:
        try:
            fetched = await asyncio.to_thread(
                fetch_url_with_curl,
                url,
                connect_timeout_seconds=min(timeout_seconds, 10),
                read_timeout_seconds=timeout_seconds,
                max_bytes=5 * 1024 * 1024,
            )
            if fetched.status_code in {401, 403, 429}:
                raise RuntimeError(f"Access blocked with status {fetched.status_code}")
            if fetched.status_code >= 400:
                raise RuntimeError(
                    f"URL fetch failed with status {fetched.status_code}"
                )
            content_type = fetched.headers.get("content-type", "")
            mime = content_type.split(";", 1)[0].strip().lower()
            if not _is_readable_text(mime=mime, body=fetched.body):
                kind = mime or "binary content"
                raise RuntimeError(
                    f"web_extract only accepts readable web pages; received {kind}. "
                    "Use content_import to import PDFs and other downloadable files."
                )
            mime = mime or "text/html"
            text = fetched.body.decode("utf-8", errors="replace")
            content = (
                html_to_markdown(text)
                if mime in {"text/html", "application/xhtml+xml"}
                else text.strip()
            )
            if not content:
                raise RuntimeError("URL extraction produced no content")
            items.append(
                WebExtractionItem(
                    source_url=url,
                    effective_url=fetched.effective_url,
                    content=content,
                    title=extract_html_title(text) if "html" in mime else None,
                    mime=mime,
                    metadata={
                        "status_code": fetched.status_code,
                        "remote_ip": fetched.remote_ip,
                        "duration_seconds": fetched.duration_seconds,
                        "redirect_count": fetched.redirect_count,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - partial results are contractual
            failures.append(
                WebItemFailure(
                    source_url=url,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            )
    return WebExtractionResult(strategy="curl", items=items, failures=failures)
