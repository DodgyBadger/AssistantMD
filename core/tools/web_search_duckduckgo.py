"""
DuckDuckGo web search tool implementation.

Provides web search capability through DuckDuckGo (free).
"""

from ddgs import DDGS
from pydantic_ai.tools import Tool
from core.constants import WEB_TOOL_SECURITY_NOTICE
from core.settings import get_default_api_timeout
from .base import BaseTool
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="web-search-duckduckgo-tool")


class WebSearchDuckDuckGo(BaseTool):
    """Web search tool using DuckDuckGo."""

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for DuckDuckGo web search."""

        def web_search(*, query: str) -> str:
            """Search DuckDuckGo for information on the given query.

            :param query: Search query to look up
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "web_search_duckduckgo"},
                )
                # Configure DuckDuckGo with timeout
                ddgs_client = DDGS(timeout=int(get_default_api_timeout()))

                # Perform search with reasonable defaults
                results = ddgs_client.text(
                    query=query,
                    max_results=3,
                    region="us-en",
                    safesearch="moderate"
                )

                if not results:
                    return f"No search results found for: {query}"

                # Format results as readable text
                formatted_results = [f"**{result['title']}**\n{result['body']}\nURL: {result['href']}"
                                   for result in results]

                return f"Search results for '{query}':\n\n" + "\n\n---\n\n".join(formatted_results)

            except Exception as e:
                return f"DuckDuckGo search error: {str(e)}"

        return Tool(web_search, name="web_search_duckduckgo")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for DuckDuckGo web search."""
        return """
## web_search_duckduckgo usage instructions

Example: web_search_duckduckgo(query="latest postgres release notes").
""" + WEB_TOOL_SECURITY_NOTICE
