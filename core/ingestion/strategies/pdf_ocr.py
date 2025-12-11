"""
Stub OCR extractor for PDFs.

Intended to call a remote OCR API (e.g., Mistral OCR). For now, returns a placeholder
so strategy plumbing can be validated without external dependencies.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict

import requests

from core.ingestion.models import ExtractedDocument, RawDocument
from core.ingestion.registry import extractor_registry
from core.settings.secrets_store import get_secret_value
from core.settings.store import get_general_settings


def _get_ocr_config() -> Dict[str, Any]:
    settings = get_general_settings()
    try:
        model = settings.get("ingestion_pdf_ocr_model").value
    except Exception:
        model = "mistral-ocr-latest"

    try:
        endpoint = settings.get("ingestion_pdf_ocr_endpoint").value
    except Exception:
        endpoint = "https://api.mistral.ai/v1/ocr"

    return {"model": model, "endpoint": endpoint}


def extract_pdf_ocr(raw: RawDocument) -> ExtractedDocument:
    """
    Call Mistral OCR API to extract text from PDF bytes.
    """
    api_key = get_secret_value("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is required for OCR extraction")

    cfg = _get_ocr_config()
    endpoint = cfg["endpoint"]
    model = cfg["model"]

    b64_pdf = base64.b64encode(raw.payload if isinstance(raw.payload, (bytes, bytearray)) else raw.payload.encode("utf-8")).decode(
        "utf-8"
    )
    data_url = f"data:application/pdf;base64,{b64_pdf}"

    payload = {
        "model": model,
        "document": {
            "type": "document_url",
            "document_url": data_url,
        },
        "include_image_base64": False,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(endpoint, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"OCR request failed ({resp.status_code}): {resp.text}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError("OCR response was not valid JSON") from exc

    pages = body.get("pages") or []
    texts = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        text_val = page.get("content") or page.get("text") or page.get("markdown")
        if isinstance(text_val, str) and text_val.strip():
            texts.append(text_val.strip())

    combined = "\n\n".join(texts).strip()
    if not combined:
        raise RuntimeError("OCR response did not contain any text content")

    meta = {
        "page_count": len(pages),
        "provider": "mistral",
        "model": model,
    }

    return ExtractedDocument(
        plain_text=combined,
        mime=raw.mime or "application/pdf",
        strategy_id="pdf_ocr",
        blocks=None,
        meta=meta,
    )


# Register extractor for explicit strategy and MIME so callers can resolve either way.
extractor_registry.register("application/pdf", extract_pdf_ocr)
extractor_registry.register("strategy:pdf_ocr", extract_pdf_ocr)
