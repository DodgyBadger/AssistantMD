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

        def search_web(*args, query: str) -> str:
            """Search DuckDuckGo for information on the given query.

            Args:
                query: The search query to look up

            Returns:
                Search results formatted as text
            """
            try:
                if args:
                    return (
                        "Positional arguments are not supported for search_web_duckduckgo. "
                        'Use named parameters, e.g. search_web_duckduckgo(query="...").'
                    )
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

        return Tool(search_web, name="search_web_duckduckgo")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for DuckDuckGo web search."""
        return (
            "Web search using DuckDuckGo: Use when you need current information or to research topics "
            "(free service). Example: search_web_duckduckgo(query=\"latest postgres release notes\"). "
            "Always use named parameters."
        ) + WEB_TOOL_SECURITY_NOTICE
