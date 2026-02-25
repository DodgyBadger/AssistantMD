"""
Shared prompt chunking helpers.

This package provides reusable, ordered text/media chunk handling for prompt assembly.
"""

from .markdown import MarkdownChunk, parse_markdown_chunks
from .image_refs import (
    MarkdownImageDecision,
    evaluate_markdown_image_policy,
    normalize_embedded_image_refs,
    resolve_local_image_path,
)
from .policy import ChunkingPolicy, default_chunking_policy
from .prompt_builder import InputFilesPromptBuildResult, build_input_files_prompt

__all__ = [
    "MarkdownChunk",
    "parse_markdown_chunks",
    "MarkdownImageDecision",
    "evaluate_markdown_image_policy",
    "normalize_embedded_image_refs",
    "resolve_local_image_path",
    "ChunkingPolicy",
    "default_chunking_policy",
    "InputFilesPromptBuildResult",
    "build_input_files_prompt",
]
