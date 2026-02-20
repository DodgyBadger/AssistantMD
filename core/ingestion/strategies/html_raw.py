"""
HTML extractor using markdownify (lightweight HTML→Markdown) with basic cleaning.
"""

from __future__ import annotations

import re

try:
    from markdownify import markdownify as md
except ImportError as exc:
    md = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _clean_html(html_source: str, clean_html: bool) -> str:
    text = html_source
    if clean_html:
        text = _SCRIPT_STYLE_RE.sub("", text)
        text = _COMMENT_RE.sub("", text)
    return text


def extract_html_markdownify(raw: RawDocument, options: dict | None = None) -> ExtractedDocument:
    """
    Convert HTML to markdown using markdownify, with optional cleaning.

    Options:
      - clean_html: bool (default True) to drop scripts/styles/comments.
      - markdownify_options: dict passed through to markdownify.markdownify
    """
    if md is None:
        raise RuntimeError(f"markdownify is required for HTML extraction: {_IMPORT_ERROR}")

    opts = options or {}
    clean_html = opts.get("clean_html", True)
    md_opts = opts.get("markdownify_options", {}) if isinstance(opts.get("markdownify_options"), dict) else {}

    source = raw.payload
    if isinstance(source, str):
        html_source = source
    elif isinstance(source, (bytes, bytearray)):
        html_source = source.decode("utf-8", errors="replace")
    else:
        raise RuntimeError("Unsupported HTML payload")

    cleaned = _clean_html(html_source, clean_html)
    markdown = md(cleaned, heading_style="ATX", **md_opts)
    markdown = markdown.strip()
    if not markdown:
        raise RuntimeError("HTML extraction produced no content")

    return ExtractedDocument(
        plain_text=markdown,
        mime=raw.mime or "text/html",
        strategy_id="html_markdownify",
        blocks=None,
        meta={"source_uri": raw.source_uri, "clean_html": clean_html},
    )


# Register extractor for HTML MIME type and explicit strategy
extractor_registry.register("text/html", extract_html_markdownify)
extractor_registry.register("strategy:html_markdownify", extract_html_markdownify)
