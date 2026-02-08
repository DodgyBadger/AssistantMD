"""
Tavily Crawl tool for intelligent website crawling.

Provides smart website crawling capabilities using Tavily's crawl API.
"""

from typing import Literal
from pydantic_ai.tools import Tool
from tavily import TavilyClient
from .base import BaseTool
from core.logger import UnifiedLogger
from core.constants import WEB_TOOL_SECURITY_NOTICE
from core.settings import get_default_api_timeout
from core.settings.secrets_store import get_secret_value

logger = UnifiedLogger(tag="tavily-crawl")


class TavilyCrawl(BaseTool):
    """Tavily Crawl tool for intelligent website crawling and content extraction."""
    
    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for website crawling."""
        tavily_api_key = get_secret_value('TAVILY_API_KEY')
        if not tavily_api_key:
            raise ValueError("Secret 'TAVILY_API_KEY' is required for TavilyCrawl.")
        
        client = TavilyClient(api_key=tavily_api_key)
        
        async def tavily_crawl(
            *,
            url: str,
            instructions: str = "Find comprehensive information and documentation",
            max_depth: int = 1,
            max_breadth: int = 5,
            limit: int = 10,
            extract_depth: Literal['basic', 'advanced'] = 'basic',
            allow_external: bool = False
        ) -> str:
            """Crawl a website and extract content from multiple pages.

            :param url: Starting URL to begin crawling from
            :param instructions: Natural language description of what content to find
            :param max_depth: Maximum crawl depth
            :param max_breadth: Links to follow per page
            :param limit: Total maximum pages to crawl
            :param extract_depth: 'basic' or 'advanced'
            :param allow_external: Whether to follow links to external domains
            """
            logger.set_sinks(["validation"]).info(
                "tool_invoked",
                data={"tool": "tavily_crawl"},
            )
            # Ensure reasonable limits
            max_depth = max(1, min(max_depth, 5))  # Tavily limit
            max_breadth = max(1, min(max_breadth, 50))  # Reasonable limit
            limit = max(1, min(limit, 50))  # Tavily limit
            
            # Tavily API has max 120 second timeout, use min of our default and 120
            timeout = min(int(get_default_api_timeout()), 120)
            
            try:
                result = client.crawl(
                    url=url,
                    instructions=instructions,
                    max_depth=max_depth,
                    max_breadth=max_breadth,
                    limit=limit,
                    extract_depth=extract_depth,
                    format='markdown',
                    allow_external=allow_external,
                    timeout=timeout
                )
            except Exception as exc:
                return f"Tavily crawl error: {exc}"
            
            if not result.get('results'):
                return f"No content could be crawled from: {url}"
            
            # Format the results
            crawled_content = [
                "# Website Crawl Results\n",
                f"**Base URL:** {result.get('base_url', url)}\n",
                f"**Pages Crawled:** {len(result['results'])}\n",
                f"**Response Time:** {result.get('response_time', 'N/A')}s\n"
            ]
            
            for i, page in enumerate(result['results'], 1):
                page_url = page.get('url', 'Unknown URL')
                content = page.get('raw_content', '')

                if content:
                    crawled_content.append(f"\n## Page {i}: {page_url}\n")
                    crawled_content.append(content)
                else:
                    crawled_content.append(f"\n## Page {i}: {page_url}\n*No content extracted*\n")

            final_content = "\n".join(crawled_content)

            return final_content
        
        return Tool(
            tavily_crawl,
            name='tavily_crawl',
            description='Intelligently crawl websites to extract comprehensive content from multiple pages.'
        )
    
    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for Tavily Crawl."""
        return """
Use when you need to comprehensively explore a website and extract content from multiple related pages.
- Crawling documentation sites for complete guides
- Exploring knowledge bases and help centers
- Conducting thorough research on company websites
- Gathering comprehensive information from structured sites

START SMALL:
- Begin with max_depth=1 and max_breadth around 3-5 to verify you're on the right section.
- Expand to deeper levels or larger breadth only in follow-up crawls once you confirm the previous run was useful.
- Keep the `limit` low (5-10 pages) initially; request another crawl if you truly need more coverage.
- Use targeted Tavily extract runs when you already know the exact pages you care about.

If you need richer content from the pages returned, re-run with `extract_depth='advanced'` after the initial pass.

IMPORTANT: If you get back only 1 page despite ambitious parameters, the site likely uses JavaScript navigation, is a single-page application, or has anti-crawling measures. In this case, inform the user that crawling isn't suitable for this site and recommend using multiple targeted extract operations on specific URLs instead.

Provide clear instructions about what content you're seeking.
Example: tavily_crawl(url="https://example.com", max_depth=1, max_breadth=3, limit=5).
""" + WEB_TOOL_SECURITY_NOTICE
