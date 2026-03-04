"""Mistral OCR extractor for image documents."""

from __future__ import annotations

from typing import Any

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry
from core.ingestion.strategies.mistral_ocr_common import extract_with_mistral_ocr


def extract_image_ocr(raw: RawDocument, options: dict[str, Any] | None = None) -> ExtractedDocument:
    include_images_override = None
    if isinstance(options, dict) and "ocr_capture_images" in options:
        include_images_override = bool(options.get("ocr_capture_images"))

    mime = (raw.mime or "").strip().lower() or "image/png"
    return extract_with_mistral_ocr(
        raw,
        strategy_id="image_ocr",
        document_type="image_url",
        document_value_key="image_url",
        data_url_mime=mime,
        model_setting_key="ingestion_ocr_model",
        endpoint_setting_key="ingestion_ocr_endpoint",
        include_image_base64_override=include_images_override,
        model_fallback_setting_keys=["ingestion_pdf_ocr_model"],
        endpoint_fallback_setting_keys=["ingestion_image_ocr_endpoint", "ingestion_pdf_ocr_endpoint"],
    )


extractor_registry.register("image/png", extract_image_ocr)
extractor_registry.register("image/jpeg", extract_image_ocr)
extractor_registry.register("image/webp", extract_image_ocr)
extractor_registry.register("image/tiff", extract_image_ocr)
extractor_registry.register("strategy:image_ocr", extract_image_ocr)
