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
    max_images_per_prompt: int
    max_image_bytes_per_image: int
    max_image_bytes_total: int
    allow_remote_images: bool


def default_chunking_policy() -> ChunkingPolicy:
    return ChunkingPolicy(
        max_images_per_prompt=get_chunking_max_images_per_prompt(),
        max_image_bytes_per_image=get_chunking_max_image_bytes_per_image(),
        max_image_bytes_total=get_chunking_max_image_bytes_total(),
        allow_remote_images=get_chunking_allow_remote_images(),
    )
