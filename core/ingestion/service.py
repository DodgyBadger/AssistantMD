"""
Ingestion service wired into runtime.
"""

from __future__ import annotations

import hashlib
import json
from typing import List
from pathlib import Path

from core.constants import ASSISTANTMD_ROOT_DIR, IMPORT_DIR
from core.ingestion.output_paths import resolve_import_output_paths
from core.ingestion.registry import importer_registry, extractor_registry
from core.ingestion.renderers import default_renderer
from core.ingestion.storage import default_storage
from core.ingestion.models import (
    JobStatus,
    RenderOptions,
    RenderMode,
    SourceKind,
)
from core.settings.secrets_store import secret_has_value
from core.settings.store import get_general_settings
from core.runtime.paths import get_data_root

from core.ingestion.jobs import (
    create_job,
    init_db,
    list_jobs,
    update_job_status,
    IngestionJob,
    get_job,
    update_job_outputs,
)
from core.logger import UnifiedLogger


class IngestionService:
    _STRATEGY_SECRET_REQUIREMENTS = {
        "pdf_ocr": "MISTRAL_API_KEY",
        "image_ocr": "MISTRAL_API_KEY",
    }

    def __init__(self):
        self.logger = UnifiedLogger(tag="ingestion")
        self._load_builtin_handlers()
        init_db()

    def enqueue_job(self, source_uri: str, vault: str, source_type: str, mime_hint: str | None, options: dict | None) -> IngestionJob:
        opts = options or {}
        return create_job(source_uri, vault, source_type, mime_hint, opts)

    def list_recent_jobs(self, limit: int = 50) -> List[IngestionJob]:
        return list_jobs(limit)

    def get_job(self, job_id: int) -> IngestionJob | None:
        return get_job(job_id)

    def mark_processing(self, job_id: int):
        update_job_status(job_id, JobStatus.PROCESSING)

    def mark_completed(self, job_id: int):
        update_job_status(job_id, JobStatus.COMPLETED)

    def mark_failed(self, job_id: int, error: str):
        update_job_status(job_id, JobStatus.FAILED, error)

    def process_job(self, job_id: int):
        """
        Process a single ingestion job end-to-end.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Ingestion job {job_id} not found")

        self.mark_processing(job_id)

        try:
            vault = job.vault
            if not vault:
                raise ValueError("Job missing vault")
            ingestion_settings = self._get_ingestion_settings()

            data_root = Path(get_data_root())
            import_root = data_root / vault / ASSISTANTMD_ROOT_DIR / IMPORT_DIR
            legacy_import_root = data_root / vault / ASSISTANTMD_ROOT_DIR / "import"
            import_root.mkdir(parents=True, exist_ok=True)

            source_path: Path | None = None
            raw_doc = None
            relative_dir = ""

            if job.source_type == SourceKind.URL.value:
                importer_fn = self._resolve_importer_for_url(job.source_uri, job.mime_hint)
                if importer_fn is None:
                    msg = "Unsupported URL ingestion source"
                    self.logger.warning(msg, metadata={"job_id": job_id, "source": job.source_uri})
                    self.mark_failed(job_id, msg)
                    return
                url_cfg = ingestion_settings.get("url", {}) if isinstance(ingestion_settings, dict) else {}
                raw_doc = importer_fn(
                    job.source_uri,
                    timeout=url_cfg.get("read_timeout_seconds", 10),
                    connect_timeout=url_cfg.get("connect_timeout_seconds", 10),
                    backend=url_cfg.get("fetch_backend", "curl"),
                )
            else:
                source_path = Path(job.source_uri)
                if not source_path.is_absolute():
                    source_path = import_root / source_path
                if not source_path.exists() and legacy_import_root.exists():
                    alt_path = legacy_import_root / Path(job.source_uri)
                    if alt_path.exists():
                        source_path = alt_path
                if not source_path.exists():
                    raise FileNotFoundError(f"Source file not found: {source_path}")

                importer_fn = self._resolve_importer(source_path, job.mime_hint)
                if importer_fn is None:
                    msg = f"Unsupported file type for ingestion: {source_path.name}"
                    self.logger.warning(msg, metadata={"job_id": job_id, "mime_hint": job.mime_hint})
                    self.mark_failed(job_id, msg)
                    return

                raw_doc = importer_fn(source_path)

            suffix = source_path.suffix.lower() if source_path else ""
            options = job.options if isinstance(job.options, dict) else {}
            pdf_mode = str(options.get("pdf_mode", "markdown")).strip().lower() if isinstance(options, dict) else "markdown"
            if source_path:
                relative_dir = self._compute_relative_import_dir(
                    source_path=source_path,
                    import_root=import_root,
                )

            if suffix == ".pdf" and pdf_mode == "page_images":
                outputs = self._render_pdf_page_images(
                    raw_doc=raw_doc,
                    vault=vault,
                    source_path=source_path,
                    relative_dir=relative_dir,
                    base_output_dir=ingestion_settings.get("output_base_dir", "Imported/"),
                    dpi=150,
                )
                update_job_outputs(job_id, outputs)
                self._cleanup_source_file(source_path=source_path, vault=vault)
                self.mark_completed(job_id)
                return

            strategies = self._get_strategies(job, suffix, ingestion_settings)
            extractor_opts = options.get("extractor_options", {}) if isinstance(options, dict) else {}
            extracted, warnings = self._run_strategies(raw_doc, strategies, ingestion_settings, extractor_opts)
            if extracted is None:
                msg = f"No extractor succeeded for {raw_doc.mime or 'unknown mime'}"
                self.logger.warning(msg, metadata={"job_id": job_id, "strategies": strategies})
                self.mark_failed(job_id, msg)
                return

            render_options = RenderOptions(
                mode=RenderMode.FULL,
                store_original=False,
                title=raw_doc.suggested_title,
                vault=vault,
                source_filename=str(source_path) if source_path else job.source_uri,
                relative_dir=relative_dir,
                path_pattern=ingestion_settings.get("output_base_dir", "Imported/"),
            )
            if warnings:
                extracted.meta.setdefault("warnings", []).extend(warnings)
            rendered = default_renderer(extracted, render_options)
            outputs = default_storage(rendered, render_options)

            update_job_outputs(job_id, outputs)
            self.mark_completed(job_id)
        except Exception as exc:
            if job.source_type == SourceKind.URL.value:
                try:
                    url_cfg = ingestion_settings.get("url", {}) if isinstance(ingestion_settings, dict) else {}
                except Exception:
                    url_cfg = {}
                self.logger.error(
                    "URL ingestion failed",
                    metadata={
                        "job_id": job_id,
                        "vault": job.vault,
                        "source_uri": job.source_uri,
                        "source_type": job.source_type,
                        "fetch_backend": url_cfg.get("fetch_backend", "curl"),
                        "connect_timeout_seconds": url_cfg.get("connect_timeout_seconds"),
                        "read_timeout_seconds": url_cfg.get("read_timeout_seconds"),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            self.mark_failed(job_id, str(exc))
            raise

    def _compute_relative_import_dir(self, source_path: Path, import_root: Path) -> str:
        try:
            source_parent = source_path.parent.resolve()
            import_root_resolved = import_root.resolve()
            if str(source_parent).startswith(str(import_root_resolved)):
                relative_dir = str(source_parent.relative_to(import_root_resolved)).strip("/")
                if relative_dir in ("", "."):
                    return ""
                return f"{relative_dir}/"
        except Exception:
            return ""
        return ""

    def _cleanup_source_file(self, source_path: Path | None, vault: str) -> None:
        if source_path is None:
            return
        try:
            data_root = Path(get_data_root())
            vault_root = (data_root / vault).resolve()
            resolved_source = source_path.resolve()
            if str(resolved_source).startswith(str(vault_root)) and resolved_source.is_file():
                resolved_source.unlink(missing_ok=True)
        except Exception:
            pass

    def _render_pdf_page_images(
        self,
        *,
        raw_doc,
        vault: str,
        source_path: Path | None,
        relative_dir: str,
        base_output_dir: str,
        dpi: int,
    ) -> list[str]:
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise RuntimeError("PyMuPDF is required for PDF page image rendering") from exc

        source_filename = str(source_path) if source_path else raw_doc.source_uri
        paths = resolve_import_output_paths(
            path_pattern=base_output_dir,
            relative_dir=relative_dir,
            source_filename=source_filename,
            title=raw_doc.suggested_title,
        )

        job_dir_rel = Path(paths.job_dir)
        pages_dir_rel = job_dir_rel / "pages"
        manifest_rel = job_dir_rel / "manifest.json"

        data_root = Path(get_data_root())
        vault_root = data_root / vault
        pages_dir_abs = vault_root / pages_dir_rel
        manifest_abs = vault_root / manifest_rel
        pages_dir_abs.mkdir(parents=True, exist_ok=True)

        payload = raw_doc.payload if isinstance(raw_doc.payload, (bytes, bytearray)) else raw_doc.payload.encode("utf-8")
        doc = fitz.open(stream=payload, filetype="pdf")
        zoom = max(1, int(dpi)) / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        page_paths: list[str] = []
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            filename = f"page_{idx:04d}.png"
            full_path = pages_dir_abs / filename
            pix.save(str(full_path))
            page_paths.append((pages_dir_rel / filename).as_posix())

        source_hash = hashlib.sha256(payload).hexdigest()
        source_mtime = None
        if source_path is not None and source_path.exists():
            try:
                source_mtime = source_path.stat().st_mtime
            except Exception:
                source_mtime = None

        manifest = {
            "source": {
                "name": source_path.name if source_path else (raw_doc.suggested_title or "import.pdf"),
                "path": str(source_path) if source_path else raw_doc.source_uri,
                "mime": raw_doc.mime or "application/pdf",
                "sha256": source_hash,
                "mtime": source_mtime,
            },
            "mode": "page_images",
            "render": {
                "format": "png",
                "dpi": int(dpi),
            },
            "page_count": len(page_paths),
            "pages": [
                {"page": idx + 1, "path": page_path}
                for idx, page_path in enumerate(page_paths)
            ],
        }
        manifest_abs.parent.mkdir(parents=True, exist_ok=True)
        manifest_abs.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return [manifest_rel.as_posix(), *page_paths]

    def _resolve_importer(self, source_path: Path, mime_hint: str | None):
        """
        Pick the first registered importer matching mime hint or file extension.
        """
        candidates = []
        if mime_hint:
            candidates.extend(importer_registry.get(mime_hint.lower()))

        suffix = source_path.suffix.lower()
        if suffix:
            candidates.extend(importer_registry.get(suffix))

        return candidates[0] if candidates else None

    def _resolve_importer_for_url(self, source_uri: str, mime_hint: str | None):
        """
        Pick importer for URLs based on scheme/mime.
        """
        candidates = []
        if mime_hint:
            candidates.extend(importer_registry.get(mime_hint.lower()))
        try:
            from urllib.parse import urlparse

            scheme = urlparse(source_uri).scheme.lower()
            if scheme:
                candidates.extend(importer_registry.get(f"scheme:{scheme}"))
        except Exception:
            pass
        candidates.extend(importer_registry.get("url"))
        return candidates[0] if candidates else None

    def _get_ingestion_settings(self) -> dict:
        """
        Map general settings entries to a simple ingestion settings dict.
        """
        general_settings = get_general_settings()
        pdf_default_strategies: list[str] = []
        ocr_model = "mistral-ocr-latest"
        ocr_endpoint = "https://api.mistral.ai/v1/ocr"
        image_default_strategies: list[str] = []
        base_output_dir = "Imported/"
        url_read_timeout_seconds = 10
        url_connect_timeout_seconds = 10
        url_fetch_backend = "curl"
        try:
            pdf_default_strategies = list(general_settings.get("ingestion_pdf_default_strategies").value)
        except Exception:
            pdf_default_strategies = []
        try:
            ocr_model = str(general_settings.get("ingestion_ocr_model").value)
        except Exception:
            try:
                ocr_model = str(general_settings.get("ingestion_pdf_ocr_model").value)
            except Exception:
                ocr_model = "mistral-ocr-latest"
        try:
            ocr_endpoint = str(general_settings.get("ingestion_ocr_endpoint").value)
        except Exception:
            try:
                ocr_endpoint = str(general_settings.get("ingestion_pdf_ocr_endpoint").value)
            except Exception:
                ocr_endpoint = "https://api.mistral.ai/v1/ocr"
        try:
            image_default_strategies = list(general_settings.get("ingestion_image_default_strategies").value)
        except Exception:
            image_default_strategies = []
        try:
            base_output_dir = str(general_settings.get("ingestion_output_path_pattern").value)
        except Exception:
            base_output_dir = "Imported/"
        try:
            url_read_timeout_seconds = int(general_settings.get("ingestion_url_read_timeout_seconds").value)
        except Exception:
            url_read_timeout_seconds = 10
        try:
            url_connect_timeout_seconds = int(general_settings.get("ingestion_url_connect_timeout_seconds").value)
        except Exception:
            url_connect_timeout_seconds = 10
        try:
            url_fetch_backend = str(general_settings.get("ingestion_url_fetch_backend").value).strip().lower() or "curl"
        except Exception:
            url_fetch_backend = "curl"

        return {
            "pdf": {
                "default_strategies": pdf_default_strategies,
                "ocr_model": ocr_model,
                "ocr_endpoint": ocr_endpoint,
            },
            "image": {
                "default_strategies": image_default_strategies,
                "ocr_model": ocr_model,
                "ocr_endpoint": ocr_endpoint,
            },
            "output_base_dir": base_output_dir,
            "url": {
                "read_timeout_seconds": max(1, url_read_timeout_seconds),
                "connect_timeout_seconds": max(1, url_connect_timeout_seconds),
                "fetch_backend": url_fetch_backend,
            },
        }

    def _resolve_extractor(self, mime: str | None):
        """
        Pick the first registered extractor for the given MIME type.
        """
        if not mime:
            return None
        candidates = extractor_registry.get(mime.lower())
        return candidates[0] if candidates else None

    def _resolve_extractor_by_strategy(self, strategy_id: str):
        """
        Pick extractor registered for a specific strategy id, falling back to MIME when strategy matches known mime.
        """
        candidates = extractor_registry.get(f"strategy:{strategy_id}")
        if candidates:
            return candidates[0]
        # Allow strategy ids that equal a MIME type
        candidates = extractor_registry.get(strategy_id.lower())
        return candidates[0] if candidates else None

    def _get_strategies(self, job: IngestionJob, suffix: str, ingestion_settings: dict) -> list[str]:
        """
        Determine strategy order for a job from options or mime defaults.
        """
        opts = job.options or {}
        strategies = opts.get("strategies")
        if isinstance(strategies, list) and strategies:
            return [str(s) for s in strategies]

        if job.source_type == SourceKind.URL.value:
            # Single HTML strategy with optional cleaning
            return ["html_markdownify"]

        # Defaults from settings
        pdf_cfg = ingestion_settings.get("pdf", {}) if isinstance(ingestion_settings, dict) else {}
        image_cfg = ingestion_settings.get("image", {}) if isinstance(ingestion_settings, dict) else {}
        if suffix == ".pdf":
            cfg_strategies = pdf_cfg.get("default_strategies") or []
            default_strats = [str(s) for s in cfg_strategies] if cfg_strategies else ["pdf_text", "pdf_ocr"]
            return default_strats
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
            cfg_strategies = image_cfg.get("default_strategies") or []
            default_strats = [str(s) for s in cfg_strategies] if cfg_strategies else ["image_ocr"]
            return default_strats
        return []

    def _run_strategies(
        self,
        raw_doc,
        strategies: list[str],
        ingestion_settings: dict,
        options: dict | None = None,
    ):
        """
        Try extractors in order; return first non-empty result.
        """
        warnings: list[str] = []
        extractor_options = options or {}
        for strat in strategies:
            secret_name = self._STRATEGY_SECRET_REQUIREMENTS.get(strat)
            if secret_name and not secret_has_value(secret_name):
                warnings.append(f"{strat}:missing_secret:{secret_name}")
                continue

            extractor_fn = self._resolve_extractor_by_strategy(strat)
            if extractor_fn is None:
                warnings.append(f"{strat}:missing")
                continue
            try:
                result = extractor_fn(raw_doc, extractor_options) if extractor_fn.__code__.co_argcount > 1 else extractor_fn(raw_doc)
            except Exception as exc:
                warnings.append(f"{strat}:error:{exc}")
                continue

            text = (result.plain_text or "").strip()
            if text:
                if strat != result.strategy_id:
                    result.strategy_id = strat
                return result, warnings if warnings else None
            warnings.append(f"{strat}:empty")

        return None, warnings if warnings else None

    def _load_builtin_handlers(self) -> None:
        """
        Import built-in source/extractor modules so they register themselves.
        """
        # Imports are intentional for side effects (registry registration).
        import core.ingestion.sources.pdf  # noqa: F401
        import core.ingestion.sources.image  # noqa: F401
        import core.ingestion.sources.web  # noqa: F401
        import core.ingestion.strategies.pdf_text  # noqa: F401
        import core.ingestion.strategies.pdf_ocr  # noqa: F401
        import core.ingestion.strategies.image_ocr  # noqa: F401
        import core.ingestion.strategies.html_raw  # noqa: F401
