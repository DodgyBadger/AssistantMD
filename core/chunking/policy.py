"""
Prompt chunking policy controls.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.settings import (
    get_chunking_allow_remote_images,
    get_chunking_max_image_bytes_per_image,
    get_chunking_max_image_bytes_total,
    get_chunking_max_images_per_prompt,
)


@dataclass(frozen=True)
class ChunkingPolicy:
    max_images_per_prompt: int = 20
    max_image_bytes_per_image: int = 5 * 1024 * 1024
    max_image_bytes_total: int = 100 * 1024 * 1024
    allow_remote_images: bool = False


def default_chunking_policy() -> ChunkingPolicy:
    return ChunkingPolicy(
        max_images_per_prompt=get_chunking_max_images_per_prompt(),
        max_image_bytes_per_image=get_chunking_max_image_bytes_per_image(),
        max_image_bytes_total=get_chunking_max_image_bytes_total(),
        allow_remote_images=get_chunking_allow_remote_images(),
    )
