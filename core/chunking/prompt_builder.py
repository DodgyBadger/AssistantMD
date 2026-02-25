"""
Build ordered prompt payloads from @input file data with markdown image support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence

from pydantic_ai import BinaryContent
from pydantic_ai.messages import UserContent

from core.constants import SUPPORTED_READ_FILE_TYPES
from .markdown import MarkdownChunk, parse_markdown_chunks
from .policy import ChunkingPolicy, default_chunking_policy

PromptInput = str | Sequence[UserContent]


@dataclass
class InputFilesPromptBuildResult:
    prompt: PromptInput
    prompt_text: str
    attached_image_count: int = 0
    attached_image_bytes: int = 0
    warnings: List[str] = field(default_factory=list)


def _normalize_input_file_lists(input_file_data: Any) -> list[list[dict[str, Any]]]:
    if not input_file_data:
        return []
    if isinstance(input_file_data, list) and input_file_data and isinstance(input_file_data[0], dict):
        return [input_file_data]
    if isinstance(input_file_data, list):
        return [item for item in input_file_data if isinstance(item, list)]
    return []


def _append_text(parts: List[UserContent], text_lines: List[str], value: str) -> None:
    if not value:
        return
    parts.append(value)
    text_lines.append(value)


def _resolve_source_markdown_path(file_data: dict[str, Any]) -> Optional[str]:
    source_path = str(file_data.get("source_path") or "").strip()
    if source_path:
        return source_path
    filepath = str(file_data.get("filepath") or "").strip()
    if not filepath:
        return None
    if "." not in Path(filepath).name:
        return f"{filepath}.md"
    return filepath


def _resolve_local_image_path(
    *,
    image_ref: str,
    source_markdown_path: str,
    vault_path: str,
) -> Optional[Path]:
    ref = (image_ref or "").strip()
    if not ref:
        return None
    if ref.startswith(("http://", "https://")):
        return None

    vault_root = Path(vault_path).resolve()
    source_path = Path(source_markdown_path)
    source_dir = source_path.parent
    candidate = Path(ref)
    if candidate.is_absolute():
        resolved = (vault_root / str(candidate).lstrip("/")).resolve()
    else:
        resolved = (vault_root / source_dir / candidate).resolve()

    if not (resolved == vault_root or vault_root in resolved.parents):
        return None
    if resolved.is_file():
        return resolved

    if "." not in candidate.name:
        for ext, kind in SUPPORTED_READ_FILE_TYPES.items():
            if kind != "image":
                continue
            fallback = resolved.with_suffix(ext)
            if fallback.is_file():
                return fallback
    return None


def _is_markdown_file(file_data: dict[str, Any]) -> bool:
    source_path = _resolve_source_markdown_path(file_data)
    if not source_path:
        return False
    return SUPPORTED_READ_FILE_TYPES.get(Path(source_path).suffix.lower()) == "markdown"


def _effective_images_policy(file_data: dict[str, Any], default_policy: str) -> str:
    raw_value = str(file_data.get("images_policy") or default_policy or "auto")
    lowered = raw_value.strip().lower()
    if lowered in {"auto", "ignore"}:
        return lowered
    return "auto"


def build_input_files_prompt(
    *,
    input_file_data: Any,
    vault_path: str,
    has_empty_directive: bool = False,
    base_prompt: Optional[str] = None,
    supports_vision: Optional[bool] = None,
    default_images_policy: str = "auto",
    policy: Optional[ChunkingPolicy] = None,
    include_file_framing: bool = True,
) -> InputFilesPromptBuildResult:
    """
    Build prompt payload from @input directive data while preserving markdown image order.
    """
    effective_policy = policy or default_chunking_policy()
    file_lists = _normalize_input_file_lists(input_file_data)
    parts: List[UserContent] = []
    text_lines: List[str] = []
    warnings: List[str] = []
    attached_count = 0
    attached_bytes = 0
    seen_images: set[str] = set()

    if base_prompt:
        _append_text(parts, text_lines, base_prompt)

    if not file_lists and not has_empty_directive:
        prompt = parts[0] if len(parts) == 1 and isinstance(parts[0], str) else parts
        if not parts:
            prompt = ""
        return InputFilesPromptBuildResult(
            prompt=prompt,
            prompt_text="".join(text_lines),
            attached_image_count=0,
            attached_image_bytes=0,
            warnings=[],
        )

    if include_file_framing:
        _append_text(parts, text_lines, "\n\n=== BEGIN INPUT_FILES ===\n")
        if not file_lists and has_empty_directive:
            _append_text(
                parts,
                text_lines,
                "--- FILE PATHS (CONTENT NOT INLINED) ---\n[NO INPUT FILES SPECIFIED IN TEMPLATE]\n",
            )
    for file_list in file_lists:
        for item in file_list:
            if not isinstance(item, dict):
                continue
            manifest = item.get("manifest")
            if manifest:
                if include_file_framing:
                    _append_text(parts, text_lines, f"--- ROUTED INPUTS ---\n{manifest}\n")
                continue

            filepath = str(item.get("filepath") or "unknown")
            found = bool(item.get("found", True))
            refs_only = bool(item.get("refs_only"))
            content = item.get("content", "")
            images_policy = _effective_images_policy(item, default_images_policy)

            if refs_only:
                missing_suffix = ""
                if not found:
                    missing_suffix = f" (missing: {item.get('error', 'File not found')})"
                if include_file_framing:
                    _append_text(
                        parts,
                        text_lines,
                        f"--- FILE PATHS (CONTENT NOT INLINED) ---\n- {filepath}{missing_suffix}\n",
                    )
                continue

            if include_file_framing:
                _append_text(parts, text_lines, f"--- FILE: {filepath} ---\n")
            if not found:
                _append_text(
                    parts,
                    text_lines,
                    f"[FILE NOT FOUND: {item.get('error', 'File not found')}]\n",
                )
                continue
            if not isinstance(content, str):
                _append_text(parts, text_lines, "[UNSUPPORTED CONTENT TYPE]\n")
                continue
            if images_policy == "ignore" or not _is_markdown_file(item):
                _append_text(parts, text_lines, f"{content}\n")
                continue

            markdown_chunks: List[MarkdownChunk] = parse_markdown_chunks(content)
            if not markdown_chunks:
                _append_text(parts, text_lines, f"{content}\n")
                continue

            source_markdown_path = _resolve_source_markdown_path(item) or filepath
            for chunk in markdown_chunks:
                if chunk.kind == "text":
                    _append_text(parts, text_lines, chunk.text)
                    continue

                image_ref = chunk.image_ref or ""
                if image_ref.startswith(("http://", "https://")):
                    marker = f"[REMOTE IMAGE REF: {image_ref}]"
                    _append_text(parts, text_lines, marker)
                    if effective_policy.allow_remote_images:
                        warnings.append(
                            f"Remote image attach not implemented yet; kept URL ref only: {image_ref}"
                        )
                    continue

                resolved_image = _resolve_local_image_path(
                    image_ref=image_ref,
                    source_markdown_path=source_markdown_path,
                    vault_path=vault_path,
                )
                if resolved_image is None:
                    _append_text(parts, text_lines, f"[MISSING IMAGE: {image_ref}]")
                    warnings.append(
                        f"Could not resolve embedded image '{image_ref}' from '{source_markdown_path}'."
                    )
                    continue

                image_key = str(resolved_image)
                if image_key in seen_images:
                    _append_text(parts, text_lines, f"[IMAGE: {resolved_image.name} (deduped)]")
                    continue

                image_blob = BinaryContent.from_path(resolved_image)
                if not image_blob.is_image:
                    _append_text(parts, text_lines, f"[NON-IMAGE REF: {image_ref}]")
                    warnings.append(
                        f"Embedded ref resolved to non-image file '{resolved_image.as_posix()}'."
                    )
                    continue

                blob_size = len(image_blob.data)
                if blob_size > effective_policy.max_image_bytes_per_image:
                    _append_text(
                        parts,
                        text_lines,
                        f"[IMAGE SKIPPED (too large): {resolved_image.name}]",
                    )
                    warnings.append(
                        f"Skipped image '{resolved_image.as_posix()}' ({blob_size} bytes) "
                        "because it exceeds per-image size limit."
                    )
                    continue
                if attached_count >= effective_policy.max_images_per_prompt:
                    _append_text(
                        parts,
                        text_lines,
                        f"[IMAGE SKIPPED (count limit): {resolved_image.name}]",
                    )
                    warnings.append(
                        "Skipped image due to max_images_per_prompt limit."
                    )
                    continue
                if attached_bytes + blob_size > effective_policy.max_image_bytes_total:
                    _append_text(
                        parts,
                        text_lines,
                        f"[IMAGE SKIPPED (byte budget): {resolved_image.name}]",
                    )
                    warnings.append(
                        "Skipped image due to max_image_bytes_total limit."
                    )
                    continue

                if supports_vision is False or images_policy == "ignore":
                    _append_text(parts, text_lines, f"[IMAGE REF: {resolved_image.as_posix()}]")
                    continue

                _append_text(
                    parts,
                    text_lines,
                    f"[IMAGE: {resolved_image.as_posix()}]",
                )
                seen_images.add(image_key)
                attached_count += 1
                attached_bytes += blob_size
                parts.append(image_blob)

            _append_text(parts, text_lines, "\n")

    if include_file_framing:
        _append_text(parts, text_lines, "=== END INPUT_FILES ===")

    prompt: PromptInput
    if not parts:
        prompt = ""
    elif len(parts) == 1 and isinstance(parts[0], str):
        prompt = parts[0]
    else:
        prompt = parts

    return InputFilesPromptBuildResult(
        prompt=prompt,
        prompt_text="".join(text_lines),
        attached_image_count=attached_count,
        attached_image_bytes=attached_bytes,
        warnings=warnings,
    )
