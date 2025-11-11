"""
Documentation access tool for AssistantMD setup and reference.

Provides AI agents with access to current, version-matched documentation
from the local /app/docs/ directory with wikilink resolution.
"""

from pathlib import Path

from pydantic import Field
from pydantic_ai import RunContext

from .base import BaseTool
import core.constants


class DocumentationAccessTool(BaseTool):
    """Tool for accessing and assembling AssistantMD documentation."""
    
    @classmethod
    def get_tool(cls, *, vault_path: str | None = None):
        """Return the Pydantic AI tool function for documentation access."""
        async def read_documentation(
            ctx: RunContext,
            path: str = Field(default="README", description="Documentation path (e.g., 'core/patterns', 'workflows/step'). Defaults to README for overview.")
        ) -> str:
            """
            Read AssistantMD documentation. 
            
            Start with README for overview and table of contents, then request specific sections as needed.
            
            Args:
                path: Documentation path relative to /app/docs/ (without .md extension)
                
            Returns:
                Documentation content
            """
            tool = cls()
            return tool._read_document(path)
        
        return read_documentation
    
    @classmethod
    def get_instructions(cls) -> str:
        """Return instructions for using the documentation access tool."""
        instructions = """
Use this tool to access AssistantMD documentation. Start by reading index.md. Then request specific pages as needed by specifying a path.
        """
        return instructions.strip()
    
    def _read_document(self, path: str) -> str:
        """Read a documentation file."""
        try:
            # Normalize path and read document
            file_path = self._normalize_path(path)
            if not file_path.exists():
                return f"Documentation not found: {path}"
            
            content = file_path.read_text(encoding='utf-8')
            return content
            
        except Exception as e:
            return f"Error reading documentation '{path}': {str(e)}"
    
    def _normalize_path(self, path: str) -> Path:
        """Normalize documentation path to full file path within docs root."""
        docs_root = Path(core.constants.DOCS_ROOT).resolve()

        normalized_path = (path or "index").strip()
        normalized_path = normalized_path.strip('/')
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
    
