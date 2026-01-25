"""
Documentation access tool for AssistantMD setup and reference.

Provides AI agents with access to current, version-matched documentation
from the local /app/docs/ directory with wikilink resolution.
"""

from pathlib import Path

from pydantic import Field
from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from .base import BaseTool
from core.runtime.paths import get_docs_root
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="documentation-access-tool")


class DocumentationAccessTool(BaseTool):
    """Tool for accessing and assembling AssistantMD documentation."""
    
    @classmethod
    def get_tool(cls, *, vault_path: str | None = None):
        """Return the Pydantic AI tool for documentation access."""
        async def read_documentation(
            ctx: RunContext,
            path: str | None = Field(
                default=None,
                description="Documentation path (e.g., 'use/workflows'). Leave empty to get a summary of the docs layout."
            )
        ) -> str:
            """
            Read AssistantMD documentation. 
                     
            Args:
                path: Documentation path relative to /app/docs/ (without .md extension)
                
            Returns:
                Documentation content
            """
            logger.set_sinks(["validation"]).info(
                "tool_invoked",
                data={"tool": "documentation_access"},
            )
            tool = cls()
            return tool._read_document(path)
        
        return Tool(read_documentation, name="documentation_access")
    
    @classmethod
    def get_instructions(cls) -> str:
        """Return instructions for using the documentation access tool."""
        instructions = """
Use this tool to read AssistantMD documentation. Call it with no arguments to receive a quick guide describing what lives under /docs and explore as needed.

        """.strip()
        return instructions.strip()
    
    def _read_document(self, path: str) -> str:
        """Read a documentation file."""
        if not path or not path.strip():
            return self._describe_docs()

        try:
            file_path = self._normalize_path(path)
        except Exception as e:
            return f"Error reading documentation '{path}': {str(e)}"

        if not file_path.exists():
            return f"Documentation not found: {path}"

        return file_path.read_text(encoding='utf-8')

    def _describe_docs(self) -> str:
        """Return a short overview of the docs folder to steer the agent."""
        docs_root = get_docs_root()

        focus_sections = [
            ("setup/workflow-setup", "Complete workflow template and walkthrough"),
            ("setup/installation", "Deployment prerequisites and docker-compose setup"),
            ("core/yaml-frontmatter", "Frontmatter keys: workflow, schedule, enabled"),
            ("core/core-directives", "Directive reference for @output-file, @tools, etc."),
            ("core/patterns", "Pattern variables like {today}, {this-week}"),
        ]

        other_sections = []
        for entry in sorted(docs_root.iterdir()):
            if entry.name.startswith('.'):
                continue
            if entry.is_dir() and entry.name not in {'setup', 'core'}:
                other_sections.append(f"{entry.name}/")
            elif entry.is_file() and entry.suffix == ".md" and entry.name not in {'index.md'}:
                other_sections.append(entry.name)

        lines = [
            "AssistantMD documentation guide:",
            "",
            "Start with these paths:",
        ]
        for path, description in focus_sections:
            lines.append(f"- {path} → {description}")

        if other_sections:
            lines.append("")
            lines.append("Other references (call by path if needed):")
            for entry in other_sections:
                lines.append(f"- {entry}")

        lines.append("")
        lines.append("Call this tool again with a specific path when you need the full file.")
        return "\n".join(lines)
    
    def _normalize_path(self, path: str) -> Path:
        """Normalize documentation path to full file path within docs root."""
        docs_root = get_docs_root().resolve()

        normalized_path = (path or "index").strip()
        normalized_path = normalized_path.strip('/')
        if normalized_path.startswith('[[') and normalized_path.endswith(']]'):
            normalized_path = normalized_path[2:-2].strip()
        if normalized_path.endswith('.md'):
            normalized_path = normalized_path[:-3]

        # Construct full path and ensure it stays within docs_root
        candidate = docs_root / f"{normalized_path}.md"
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(docs_root)
        except ValueError:
            raise ValueError("Documentation path outside of docs directory")

        return resolved_candidate
    
