"""Mistral OCR extractor for PDFs."""

from __future__ import annotations

from typing import Any

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry
from core.ingestion.strategies.mistral_ocr_common import extract_with_mistral_ocr


def extract_pdf_ocr(raw: RawDocument, options: dict[str, Any] | None = None) -> ExtractedDocument:
    include_images_override = None
    if isinstance(options, dict) and "ocr_capture_images" in options:
        include_images_override = bool(options.get("ocr_capture_images"))

    return extract_with_mistral_ocr(
        raw,
        strategy_id="pdf_ocr",
        document_type="document_url",
        document_value_key="document_url",
        data_url_mime="application/pdf",
        model_setting_key="ingestion_ocr_model",
        endpoint_setting_key="ingestion_ocr_endpoint",
        include_image_base64_override=include_images_override,
        model_fallback_setting_keys=["ingestion_pdf_ocr_model"],
        endpoint_fallback_setting_keys=["ingestion_pdf_ocr_endpoint"],
    )


# Register extractor for explicit strategy and MIME so callers can resolve either way.
extractor_registry.register("application/pdf", extract_pdf_ocr)
extractor_registry.register("strategy:pdf_ocr", extract_pdf_ocr)
