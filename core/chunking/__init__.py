"""
Shared prompt chunking helpers.

This package provides reusable, ordered text/media chunk handling for prompt assembly.
"""

from .markdown import MarkdownChunk, parse_markdown_chunks
from .policy import ChunkingPolicy, default_chunking_policy
from .prompt_builder import InputFilesPromptBuildResult, build_input_files_prompt

__all__ = [
    "MarkdownChunk",
    "parse_markdown_chunks",
    "ChunkingPolicy",
    "default_chunking_policy",
    "InputFilesPromptBuildResult",
    "build_input_files_prompt",
]

