"""
HTML extractor using markitdown to convert to markdown text.
"""

from __future__ import annotations

import io
import re
from typing import Any

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry

try:
    from markitdown import MarkItDown
except ImportError as exc:
    MarkItDown = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\\1>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def extract_html_markitdown(raw: RawDocument, options: dict | None = None) -> ExtractedDocument:
    """
    Convert HTML to markdown using markitdown, with optional cleaning.

    Options:
      - clean_html: bool (default True) to enable readability-style filtering.
    """
    if MarkItDown is None:
        raise RuntimeError(f"markitdown is required for HTML extraction: {_IMPORT_ERROR}")

    opts = options or {}
    clean_html = opts.get("clean_html", True)

    source = raw.payload
    if isinstance(source, str):
        html = source
    elif isinstance(source, (bytes, bytearray)):
        html = source.decode("utf-8", errors="replace")
    else:
        raise RuntimeError("Unsupported HTML payload")

    if clean_html:
        # Minimal cleaning: drop scripts/styles/comments to reduce noise
        html = _SCRIPT_STYLE_RE.sub("", html)
        html = _COMMENT_RE.sub("", html)

    md = MarkItDown()
    result = md.convert(io.BytesIO(html.encode("utf-8")), content_type="text/html")
    text = result.text_content or ""
    if not text.strip():
        raise RuntimeError("HTML extraction produced no content")

    return ExtractedDocument(
        plain_text=text.strip(),
        mime=raw.mime or "text/html",
        strategy_id="html_markitdown",
        blocks=None,
        meta={"source_uri": raw.source_uri, "clean_html": clean_html},
    )


# Register extractor for HTML MIME type and explicit strategy
extractor_registry.register("text/html", extract_html_markitdown)
extractor_registry.register("strategy:html_markitdown", extract_html_markitdown)
