from __future__ import annotations

from dataclasses import dataclass, field
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any

from core.constants import ASSISTANTMD_ROOT_DIR, CONTEXT_TEMPLATE_DIR
from core.directives.parser import parse_directives
from core.runtime.paths import get_system_root
from core.logger import UnifiedLogger
from core.workflow.parser import parse_frontmatter, parse_markdown_sections
from core.utils.hash import hash_file_content

logger = UnifiedLogger(tag="context-templates")


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
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    instructions: Optional[str] = None
    chat_instructions: Optional[str] = None
    template_section: Optional[str] = None
    template_body: Optional[str] = None
    directives: Dict[str, List[str]] = field(default_factory=dict)
    template_sections: List["TemplateSection"] = field(default_factory=list)


@dataclass
class TemplateSection:
    """Individual context template section (one per ## heading)."""

    name: str
    content: str
    cleaned_content: str
    directives: Dict[str, List[str]] = field(default_factory=dict)


def _ensure_md_suffix(name: str) -> str:
    """Normalize template names to include .md extension."""
    if not name.lower().endswith(".md"):
        return f"{name}.md"
    return name


def _hash_content(content: str) -> str:
    return hash_file_content(content, length=None)


def _extract_schema_block(content: str) -> Optional[str]:
    """
    Extract first fenced block labeled yaml or json from the template.
    Returns raw block content or None.
    """
    lines = content.splitlines()
    in_block = False
    block_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("```"):
                lang = stripped[3:].strip()
                if lang in ("yaml", "json", ""):
                    in_block = True
                    block_lines = []
            continue

        # inside block
        if stripped.startswith("```"):
            break
        block_lines.append(line)

    if not block_lines:
        return None
    return "\n".join(block_lines).strip()


def _parse_template_content(content: str) -> tuple[Dict[str, Any], Dict[str, str], str]:
    """Parse optional frontmatter and markdown sections for templates."""
    stripped = content.lstrip()
    if stripped.startswith("---"):
        frontmatter, remaining = parse_frontmatter(content)
    else:
        frontmatter = {}
        remaining = content

    sections = parse_markdown_sections(remaining, "##")
    return frontmatter, sections, remaining


def _select_instruction_and_template_sections(
    sections: Dict[str, str],
    remaining: str,
) -> tuple[Optional[str], Optional[str], List[TemplateSection]]:
    """Pick context instructions, chat instructions, and template sections."""
    if not sections:
        fallback_parsed = parse_directives(remaining or "")
        if fallback_parsed.cleaned_content.strip():
            fallback_section = TemplateSection(
                name="Template",
                content=remaining or "",
                cleaned_content=fallback_parsed.cleaned_content,
                directives=fallback_parsed.directives,
            )
            return None, None, [fallback_section]
        return None, None, []

    section_items = list(sections.items())
    context_instructions: Optional[str] = None
    chat_instructions: Optional[str] = None
    context_sections: List[str] = []
    instruction_section_names: List[str] = []
    for section_name, _ in section_items:
        lowered = section_name.strip().lower()
        if "instructions" in lowered:
            instruction_section_names.append(section_name)
        if lowered == "chat instructions":
            chat_instructions = sections.get(section_name, "").strip() or None
        if lowered == "context instructions":
            context_sections.append(section_name)

    if context_sections:
        context_instructions = "\n\n".join(
            [
                sections.get(section_name, "").strip()
                for section_name in context_sections
                if sections.get(section_name, "").strip()
            ]
        ).strip() or None

    template_sections: List[TemplateSection] = []
    for section_name, section_content in section_items:
        if section_name in instruction_section_names:
            continue
        parsed = parse_directives(section_content or "")
        template_sections.append(
            TemplateSection(
                name=section_name,
                content=section_content,
                cleaned_content=parsed.cleaned_content,
                directives=parsed.directives,
            )
        )

    return context_instructions, chat_instructions, template_sections


def _read_template(path: Path, name: str, source: str) -> TemplateRecord:
    content = path.read_text(encoding="utf-8")
    frontmatter, sections, remaining = _parse_template_content(content)
    instructions, chat_instructions, template_sections = _select_instruction_and_template_sections(
        sections,
        remaining,
    )
    first_section = template_sections[0] if template_sections else None
    return TemplateRecord(
        name=name,
        content=content,
        source=source,
        path=path,
        sha256=_hash_content(content),
        schema_block=_extract_schema_block(content),
        frontmatter=frontmatter,
        instructions=instructions,
        chat_instructions=chat_instructions,
        template_section=first_section.name if first_section else None,
        template_body=first_section.cleaned_content if first_section else None,
        directives=first_section.directives if first_section else {},
        template_sections=template_sections,
    )


def load_template(
    name: Optional[str],
    vault_path: Optional[Path],
    system_root: Optional[Path] = None,
) -> TemplateRecord:
    """
    Resolve a template by name with vault → system → builtin priority.

    Args:
        name: Template filename (required)
        vault_path: Path to the active vault (root). If None, vault lookup is skipped.
        system_root: Optional system root override (defaults to runtime system root).

    Returns:
        TemplateRecord describing the resolved template.
    """
    if not name:
        raise ValueError("Template name is required for load_template")

    normalized = _ensure_md_suffix(name)

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

    raise FileNotFoundError(f"Template '{normalized}' not found in vault or system templates")


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

    Copies all files from core/context/template_seed into system ContextTemplates
    if they are not already present. Does not overwrite existing templates.
    """
    try:
        sys_root = system_root or get_system_root()
    except Exception as exc:  # pragma: no cover - defensive during bootstrap
        logger.warning(f"System root unavailable while seeding templates: {exc}")
        return

    target_dir = Path(sys_root) / SYSTEM_TEMPLATE_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if not SEED_TEMPLATE_DIR.exists():
        logger.warning(f"Seed template directory missing: {SEED_TEMPLATE_DIR}")
        return

    for seed_path in SEED_TEMPLATE_DIR.iterdir():
        if not seed_path.is_file():
            continue
        target_path = target_dir / seed_path.name
        if target_path.exists():
            continue  # Preserve existing templates
        try:
            shutil.copyfile(seed_path, target_path)
            logger.info(f"Seeded context template to {target_path}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Failed to seed system template {target_path}: {exc}")
