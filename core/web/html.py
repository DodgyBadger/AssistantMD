"""Reusable HTML cleaning and Markdown conversion."""

from __future__ import annotations

import re
from typing import Any, cast

from markdownify import markdownify

from core.web.errors import WebExtractionError


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def html_to_markdown(
    html_source: str,
    *,
    clean_html: bool = True,
    markdownify_options: dict[str, object] | None = None,
) -> str:
    """Convert HTML into non-empty Markdown using shared cleaning policy."""
    source = html_source
    if clean_html:
        source = _SCRIPT_STYLE_RE.sub("", source)
        source = _COMMENT_RE.sub("", source)
    options = dict(markdownify_options or {})
    converted = markdownify(source, heading_style="ATX", **cast(Any, options)).strip()
    if not converted:
        raise WebExtractionError("HTML extraction produced no content")
    return converted


def extract_html_title(html_source: str) -> str | None:
    """Return a compact HTML title when present."""
    match = _TITLE_RE.search(html_source)
    if not match:
        return None
    title = " ".join(match.group(1).split()).strip()
    return title or None
