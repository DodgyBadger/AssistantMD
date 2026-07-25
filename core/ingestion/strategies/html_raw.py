"""
HTML extractor using markdownify (lightweight HTML→Markdown) with basic cleaning.
"""

from __future__ import annotations

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry
from core.web.html import html_to_markdown


def extract_html_markdownify(
    raw: RawDocument, options: dict | None = None
) -> ExtractedDocument:
    """
    Convert HTML to markdown using markdownify, with optional cleaning.

    Options:
      - clean_html: bool (default True) to drop scripts/styles/comments.
      - markdownify_options: dict passed through to markdownify.markdownify
    """
    opts = options or {}
    clean_html = opts.get("clean_html", True)
    md_opts = (
        opts.get("markdownify_options", {})
        if isinstance(opts.get("markdownify_options"), dict)
        else {}
    )

    source = raw.payload
    if isinstance(source, str):
        html_source = source
    elif isinstance(source, bytes | bytearray):
        html_source = source.decode("utf-8", errors="replace")
    else:
        raise RuntimeError("Unsupported HTML payload")

    markdown = html_to_markdown(
        html_source,
        clean_html=bool(clean_html),
        markdownify_options=md_opts,
    )

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
