"""
Tavily web search tool implementation.

Provides web search capability through Tavily API (premium).
"""

import httpx
from pydantic_ai.tools import Tool
from core.constants import WEB_TOOL_SECURITY_NOTICE
from core.settings import get_default_api_timeout
from .base import BaseTool
from core.settings.secrets_store import get_secret_value
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="web-search-tavily-tool")


class WebSearchTavily(BaseTool):
    """Web search tool using Tavily API."""

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for Tavily web search."""
        tavily_api_key = get_secret_value('TAVILY_API_KEY')
        if not tavily_api_key:
            raise ValueError("Secret 'TAVILY_API_KEY' is required for Tavily web search.")

        def search_web(*args, query: str) -> str:
            """Search Tavily for information on the given query.

            Args:
                query: The search query to look up

            Returns:
                Search results formatted as text
            """
            try:
                if args:
                    return (
                        "Positional arguments are not supported for search_web_tavily. "
                        'Use named parameters, e.g. search_web_tavily(query="...").'
                    )
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "web_search_tavily"},
                )
                # Make request to Tavily API
                with httpx.Client(timeout=float(get_default_api_timeout())) as client:
                    response = client.post(
                        "https://api.tavily.com/search",
                        headers={"Content-Type": "application/json"},
                        json={
                            "api_key": tavily_api_key,
                            "query": query,
                            "max_results": 3,
                            "search_depth": "basic",
                            "include_answer": False,
                            "include_raw_content": False
                        }
                    )
                    response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                if not results:
                    return f"No search results found for: {query}"

                # Format results as readable text
                formatted_results = [f"**{result['title']}**\n{result['content']}\nURL: {result['url']}"
                                   for result in results]

                return f"Search results for '{query}':\n\n" + "\n\n---\n\n".join(formatted_results)

            except httpx.HTTPError as e:
                return f"Tavily API error: {str(e)}"
            except Exception as e:
                return f"Tavily search error: {str(e)}"

        return Tool(search_web, name="search_web_tavily")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for Tavily web search."""
        return (
            "Web search using Tavily API: Use when you need current information or to research topics "
            "(premium service). Example: search_web_tavily(query=\"latest fastapi release\"). "
            "Always use named parameters."
        ) + WEB_TOOL_SECURITY_NOTICE
