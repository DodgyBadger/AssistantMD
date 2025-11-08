"""
Shared utilities for file operations tools.

Provides security validation and path resolution for all file operations.
"""

import os
import tiktoken


def validate_and_resolve_path(path: str, vault_path: str) -> str:
    """Validate path and resolve to full path within vault boundaries.

    Args:
        path: Relative file path to validate
        vault_path: Root vault directory path

    Returns:
        Absolute resolved path within vault

    Raises:
        ValueError: If path fails security validation
    """
    # Security validations
    if '..' in path:
        raise ValueError("Path traversal not allowed - '..' found in path")

    if path.startswith('/'):
        raise ValueError("Absolute paths not allowed")

    # Markdown extension enforcement
    if '.' in os.path.basename(path):
        if not path.endswith('.md'):
            raise ValueError("Only .md files are allowed. Please use '.md' extension for all files.")

    # Resolve to full path
    full_path = os.path.join(vault_path, path)
    resolved_path = os.path.abspath(full_path)

    # Ensure the resolved path is within vault boundaries
    vault_abs = os.path.abspath(vault_path)
    if not resolved_path.startswith(vault_abs + os.sep) and resolved_path != vault_abs:
        raise ValueError("Path escapes vault boundaries")

    return resolved_path


def estimate_token_count(text: str, encoding_name: str = "cl100k_base") -> int:
    """
    Estimate token count for text using tiktoken.

    Args:
        text: The text content to count tokens for
        encoding_name: The tiktoken encoding to use (default: cl100k_base for GPT-4/Claude-like models)

    Returns:
        Estimated token count

    Note:
        Uses cl100k_base encoding by default, which is appropriate for:
        - GPT-4, GPT-4o, GPT-3.5-turbo
        - Claude models (approximate)
        - Most modern LLMs
    """
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))


def get_tool_instructions(tool_classes):
    """Compose a user-facing capability summary for enabled tools."""
    if not tool_classes:
        return ""

    instructions = ["You have access to the following capabilities:"]
    for tool_class in tool_classes:
        instructions.append(f"## {tool_class.get_instructions()}")
    return "\n\n".join(instructions)
