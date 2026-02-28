"""
Shared helpers for image attachment and tool payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic_ai import BinaryContent

from core.chunking.policy import ChunkingPolicy
from core.utils.hash import hash_bytes


def format_image_ref_marker(path: str) -> str:
    return f"[IMAGE REF: {path}]"


def format_remote_image_ref_marker(url: str) -> str:
    return f"[REMOTE IMAGE REF: {url}]"


def format_missing_image_marker(ref: str) -> str:
    return f"[MISSING IMAGE: {ref}]"


def format_image_marker(path: str) -> str:
    return f"[IMAGE: {path}]"


def format_image_deduped_marker(name: str) -> str:
    return f"[IMAGE: {name} (deduped)]"


def format_image_non_image_marker(path: str) -> str:
    return f"[NON-IMAGE REF: {path}]"


def format_image_skipped_marker(reason: str, name: str) -> str:
    return f"[IMAGE SKIPPED ({reason}): {name}]"


@dataclass(frozen=True)
class ImageAttachmentDecision:
    marker: str
    image_blob: Optional[BinaryContent]
    warnings: list[str]
    attached: bool
    size_bytes: int
    image_key: str
    image_hash: Optional[str]


def evaluate_image_attachment(
    *,
    image_path: Path,
    policy: ChunkingPolicy,
    images_policy: str,
    supports_vision: Optional[bool],
    seen_images: set[str],
    seen_image_hashes: set[str],
    attached_count: int,
    attached_bytes: int,
) -> ImageAttachmentDecision:
    image_key = str(image_path)
    image_name = image_path.name

    if image_key in seen_images:
        return ImageAttachmentDecision(
            marker=format_image_deduped_marker(image_name),
            image_blob=None,
            warnings=[],
            attached=False,
            size_bytes=0,
            image_key=image_key,
            image_hash=None,
        )

    image_blob = BinaryContent.from_path(image_path)
    if not image_blob.is_image:
        return ImageAttachmentDecision(
            marker=format_image_non_image_marker(image_path.as_posix()),
            image_blob=None,
            warnings=[
                f"Input image resolved to non-image '{image_path.as_posix()}'."
            ],
            attached=False,
            size_bytes=0,
            image_key=image_key,
            image_hash=None,
        )

    image_hash = hash_bytes(image_blob.data, length=None)
    if image_hash in seen_image_hashes:
        return ImageAttachmentDecision(
            marker=format_image_deduped_marker(image_name),
            image_blob=None,
            warnings=[],
            attached=False,
            size_bytes=0,
            image_key=image_key,
            image_hash=image_hash,
        )

    blob_size = len(image_blob.data)
    if blob_size > policy.max_image_bytes_per_image:
        return ImageAttachmentDecision(
            marker=format_image_skipped_marker("too large", image_name),
            image_blob=None,
            warnings=[
                f"Skipped image '{image_path.as_posix()}' ({blob_size} bytes) "
                "because it exceeds per-image size limit."
            ],
            attached=False,
            size_bytes=0,
            image_key=image_key,
            image_hash=image_hash,
        )
    if attached_count >= policy.max_images_per_prompt:
        return ImageAttachmentDecision(
            marker=format_image_skipped_marker("count limit", image_name),
            image_blob=None,
            warnings=["Skipped image due to max_images_per_prompt limit."],
            attached=False,
            size_bytes=0,
            image_key=image_key,
            image_hash=image_hash,
        )
    if attached_bytes + blob_size > policy.max_image_bytes_total:
        return ImageAttachmentDecision(
            marker=format_image_skipped_marker("byte budget", image_name),
            image_blob=None,
            warnings=["Skipped image due to max_image_bytes_total limit."],
            attached=False,
            size_bytes=0,
            image_key=image_key,
            image_hash=image_hash,
        )

    if supports_vision is False or images_policy == "ignore":
        return ImageAttachmentDecision(
            marker=format_image_ref_marker(image_path.as_posix()),
            image_blob=None,
            warnings=[],
            attached=False,
            size_bytes=0,
            image_key=image_key,
            image_hash=image_hash,
        )

    return ImageAttachmentDecision(
        marker=format_image_marker(image_path.as_posix()),
        image_blob=image_blob,
        warnings=[],
        attached=True,
        size_bytes=blob_size,
        image_key=image_key,
        image_hash=image_hash,
    )


@dataclass(frozen=True)
class ImageToolPayload:
    note: str
    image_blob: BinaryContent
    metadata: dict[str, Any]


def build_image_tool_payload(*, image_path: Path, vault_path: str) -> ImageToolPayload:
    relative_path = image_path.resolve().relative_to(Path(vault_path).resolve())
    relative_display = relative_path.as_posix()
    image_blob = BinaryContent.from_path(image_path)
    note = (
        f"Attached image from '{relative_display}'. Use this image to answer the user's request."
    )
    metadata = {
        "filepath": relative_display,
        "media_type": image_blob.media_type,
        "size_bytes": len(image_blob.data),
    }
    return ImageToolPayload(note=note, image_blob=image_blob, metadata=metadata)
