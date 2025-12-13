from __future__ import annotations

from dataclasses import dataclass
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Optional, List

import yaml

from core.constants import ASSISTANTMD_ROOT_DIR, CONTEXT_TEMPLATE_DIR
from core.runtime.paths import get_system_root
from core.logger import UnifiedLogger

logger = UnifiedLogger(tag="context-templates")


DEFAULT_TEMPLATE_NAME = "chat_compiler.md"
VAULT_TEMPLATE_SUBDIR = CONTEXT_TEMPLATE_DIR
SYSTEM_TEMPLATE_SUBDIR = CONTEXT_TEMPLATE_DIR
SEED_TEMPLATE_DIR = Path(__file__).parent / "template_seed"


@dataclass
class TemplateRecord:
    """Resolved template with source metadata."""

    name: str
    content: str
    source: str  # "vault", "system", or "builtin"
    path: Optional[Path]
    sha256: str
    schema_block: Optional[str] = None  # raw YAML/JSON block if present


def _ensure_md_suffix(name: str) -> str:
    """Normalize template names to include .md extension."""
    if not name.lower().endswith(".md"):
        return f"{name}.md"
    return name


def _hash_content(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _extract_schema_block(content: str) -> Optional[str]:
    """
    Extract first fenced block labeled yaml or json from the template.
    Returns raw block content or None.
    """
    lines = content.splitlines()
    in_block = False
    block_lang = None
    block_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("```"):
                lang = stripped[3:].strip()
                if lang in ("yaml", "json", ""):
                    in_block = True
                    block_lang = lang or None
                    block_lines = []
            continue

        # inside block
        if stripped.startswith("```"):
            break
        block_lines.append(line)

    if not block_lines:
        return None
    return "\n".join(block_lines).strip()


def _builtin_default_template(requested_name: str) -> TemplateRecord:
    """Fallback template if no on-disk template is found."""
    content = """# Chat Context Compiler

You compile a concise working context for the next model call.

Return JSON with exactly these keys:
{
  "constraints": ["string"],
  "plan": "string",
  "recent_turns": [{"speaker": "string", "text": "string"}],
  "tool_results": [{"tool": "string", "result": "string"}],
  "reflections": [{"observation": "string", "adjustment": "string"}],
  "latest_input": "string"
}
"""
    return TemplateRecord(
        name=requested_name,
        content=content,
        source="builtin",
        path=None,
        sha256=_hash_content(content),
        schema_block=_extract_schema_block(content),
    )


def _read_template(path: Path, name: str, source: str) -> TemplateRecord:
    content = path.read_text(encoding="utf-8")
    return TemplateRecord(
        name=name,
        content=content,
        source=source,
        path=path,
        sha256=_hash_content(content),
        schema_block=_extract_schema_block(content),
    )


def load_template(
    name: Optional[str],
    vault_path: Optional[Path],
    system_root: Optional[Path] = None,
) -> TemplateRecord:
    """
    Resolve a template by name with vault → system → builtin priority.

    Args:
        name: Template filename or None to use default
        vault_path: Path to the active vault (root). If None, vault lookup is skipped.
        system_root: Optional system root override (defaults to runtime system root).

    Returns:
        TemplateRecord describing the resolved template.
    """
    normalized = _ensure_md_suffix(name or DEFAULT_TEMPLATE_NAME)

    # Try vault-scoped template
    if vault_path:
        vault_template = (
            Path(vault_path)
            / ASSISTANTMD_ROOT_DIR
            / VAULT_TEMPLATE_SUBDIR
            / normalized
        )
        if vault_template.exists():
            logger.info(f"Using vault template: {vault_template}")
            return _read_template(vault_template, normalized, source="vault")

    # Try system template
    try:
        system_root = system_root or get_system_root()
    except Exception as exc:  # pragma: no cover - defensive: bootstrap not ready
        logger.warning(f"System root unavailable: {exc}")
        system_root = None

    if system_root:
        system_template = (
            Path(system_root) / SYSTEM_TEMPLATE_SUBDIR / normalized
        )
        if system_template.exists():
            logger.info(f"Using system template: {system_template}")
            return _read_template(system_template, normalized, source="system")

    # Fall back to builtin default
    logger.info(f"Falling back to builtin template: {normalized}")
    return _builtin_default_template(normalized)


def list_templates(
    vault_path: Optional[Path],
    system_root: Optional[Path] = None,
) -> List[TemplateRecord]:
    """
    List available templates from vault and system locations (no fallback/builtin).
    """
    records: List[TemplateRecord] = []
    normalized_root = Path(vault_path) if vault_path else None

    # Vault templates
    if normalized_root:
        vault_dir = normalized_root / ASSISTANTMD_ROOT_DIR / VAULT_TEMPLATE_SUBDIR
        if vault_dir.exists():
            for path in sorted(vault_dir.glob("*.md")):
                try:
                    records.append(_read_template(path, path.name, "vault"))
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(f"Failed to read vault template {path}: {exc}")

    # System templates
    try:
        sys_root = system_root or get_system_root()
    except Exception as exc:  # pragma: no cover
        logger.warning(f"System root unavailable while listing templates: {exc}")
        sys_root = None

    if sys_root:
        system_dir = Path(sys_root) / SYSTEM_TEMPLATE_SUBDIR
        if system_dir.exists():
            for path in sorted(system_dir.glob("*.md")):
                try:
                    records.append(_read_template(path, path.name, "system"))
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(f"Failed to read system template {path}: {exc}")

    return records


def seed_system_templates(system_root: Optional[Path] = None) -> None:
    """
    Ensure system templates directory exists with seeded defaults.

    Seeds the default chat compiler template into system ContextTemplates
    if no file exists for that name.
    """
    try:
        sys_root = system_root or get_system_root()
    except Exception as exc:  # pragma: no cover - defensive during bootstrap
        logger.warning(f"System root unavailable while seeding templates: {exc}")
        return

    target_dir = Path(sys_root) / SYSTEM_TEMPLATE_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / DEFAULT_TEMPLATE_NAME
    if target_path.exists():
        return

    seed_path = SEED_TEMPLATE_DIR / DEFAULT_TEMPLATE_NAME
    try:
        if seed_path.exists():
            shutil.copyfile(seed_path, target_path)
            logger.info(f"Seeded default context template to {target_path}")
        else:
            # Fallback to builtin content if seed file is missing
            target_path.write_text(_builtin_default_template(DEFAULT_TEMPLATE_NAME).content, encoding="utf-8")
            logger.warning(f"Seed template missing; wrote builtin default to {target_path}")
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to seed system template {target_path}: {exc}")
