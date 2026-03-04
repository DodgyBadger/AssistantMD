from __future__ import annotations

import base64
import json
from typing import Any, Dict

import requests

from core.ingestion.models import ExtractedDocument, RawDocument
from core.settings.secrets_store import get_secret_value
from core.settings.store import get_general_settings


def _setting_bool(settings: Any, key: str, default: bool) -> bool:
    try:
        value = settings.get(key).value
    except Exception:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _extract_base64_and_media(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, None
    raw = value.strip()
    if not raw:
        return None, None
    if raw.startswith("data:"):
        # Expected shape: data:<media_type>;base64,<payload>
        prefix, _, payload = raw.partition(",")
        if not payload:
            return None, None
        media_type = None
        if ";" in prefix:
            media_type = prefix[5:].split(";", 1)[0].strip() or None
        return payload.strip(), media_type
    return raw, None


def _collect_page_images(page: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    image_index = 1

    raw_images = page.get("images")
    if isinstance(raw_images, list):
        for image in raw_images:
            if isinstance(image, dict):
                base64_value, inferred_media = _extract_base64_and_media(
                    image.get("image_base64") or image.get("base64") or image.get("data")
                )
                source_name = (
                    image.get("name")
                    or image.get("filename")
                    or image.get("file_name")
                    or image.get("id")
                    or image.get("image_id")
                )
                media_type = (
                    image.get("mime_type")
                    or image.get("media_type")
                    or inferred_media
                    or "image/png"
                )
            else:
                base64_value, inferred_media = _extract_base64_and_media(image)
                source_name = None
                media_type = inferred_media or "image/png"
            if not base64_value:
                continue
            items.append(
                {
                    "page_number": page_number,
                    "image_index": image_index,
                    "media_type": str(media_type),
                    "data_base64": base64_value,
                    "source_name": str(source_name).strip() if source_name else None,
                }
            )
            image_index += 1

    single_base64_value, single_media = _extract_base64_and_media(page.get("image_base64"))
    if single_base64_value:
        items.append(
            {
                "page_number": page_number,
                "image_index": image_index,
                "media_type": str(single_media or page.get("mime_type") or "image/png"),
                "data_base64": single_base64_value,
            }
        )

    return items


def get_mistral_ocr_config(
    model_setting_key: str,
    endpoint_setting_key: str,
    model_fallback_setting_keys: list[str] | None = None,
    endpoint_fallback_setting_keys: list[str] | None = None,
    default_model: str = "mistral-ocr-latest",
    default_endpoint: str = "https://api.mistral.ai/v1/ocr",
) -> Dict[str, str]:
    settings = get_general_settings()
    try:
        model = str(settings.get(model_setting_key).value)
    except Exception:
        model = default_model
        for fallback_key in model_fallback_setting_keys or []:
            try:
                model = str(settings.get(fallback_key).value)
                break
            except Exception:
                continue

    try:
        endpoint = str(settings.get(endpoint_setting_key).value)
    except Exception:
        endpoint = default_endpoint
        for fallback_key in endpoint_fallback_setting_keys or []:
            try:
                endpoint = str(settings.get(fallback_key).value)
                break
            except Exception:
                continue

    return {"model": model, "endpoint": endpoint}


def extract_with_mistral_ocr(
    raw: RawDocument,
    *,
    strategy_id: str,
    document_type: str,
    document_value_key: str,
    data_url_mime: str,
    model_setting_key: str,
    endpoint_setting_key: str,
    include_image_base64_override: bool | None = None,
    model_fallback_setting_keys: list[str] | None = None,
    endpoint_fallback_setting_keys: list[str] | None = None,
) -> ExtractedDocument:
    api_key = get_secret_value("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is required for OCR extraction")

    cfg = get_mistral_ocr_config(
        model_setting_key=model_setting_key,
        endpoint_setting_key=endpoint_setting_key,
        model_fallback_setting_keys=model_fallback_setting_keys,
        endpoint_fallback_setting_keys=endpoint_fallback_setting_keys,
    )
    endpoint = cfg["endpoint"]
    model = cfg["model"]
    settings = get_general_settings()
    include_image_base64 = (
        bool(include_image_base64_override)
        if include_image_base64_override is not None
        else _setting_bool(settings, "ingestion_ocr_capture_images", False)
    )

    payload_bytes = raw.payload if isinstance(raw.payload, (bytes, bytearray)) else raw.payload.encode("utf-8")
    data_url = f"data:{data_url_mime};base64,{base64.b64encode(payload_bytes).decode('utf-8')}"

    request_payload = {
        "model": model,
        "document": {
            "type": document_type,
            document_value_key: data_url,
        },
        "include_image_base64": include_image_base64,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(endpoint, headers=headers, data=json.dumps(request_payload), timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"OCR request failed ({resp.status_code}): {resp.text}")

    try:
        body: Dict[str, Any] = resp.json()
    except ValueError as exc:
        raise RuntimeError("OCR response was not valid JSON") from exc

    pages = body.get("pages") or []
    texts: list[str] = []
    ocr_images: list[dict[str, Any]] = []
    for page_idx, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        text_val = page.get("content") or page.get("text") or page.get("markdown")
        if isinstance(text_val, str) and text_val.strip():
            texts.append(text_val.strip())
        page_number_raw = page.get("index") or page.get("page_number") or page_idx
        try:
            page_number = int(page_number_raw)
        except Exception:
            page_number = page_idx
        if include_image_base64:
            ocr_images.extend(_collect_page_images(page, page_number))

    combined = "\n\n".join(texts).strip()
    if not combined:
        raise RuntimeError("OCR response did not contain any text content")

    meta = {
        "page_count": len(pages),
        "ocr_image_count": len(ocr_images),
        "ocr_images": ocr_images,
        "provider": "mistral",
        "model": model,
    }

    return ExtractedDocument(
        plain_text=combined,
        mime=raw.mime or data_url_mime,
        strategy_id=strategy_id,
        blocks=None,
        meta=meta,
    )
