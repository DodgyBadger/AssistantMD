"""
Tavily Extract tool for content extraction from URLs.

Provides advanced content extraction capabilities using Tavily's extract API.
"""

from typing import List, Union, Literal
from pydantic_ai.tools import Tool
from tavily import TavilyClient
from .base import BaseTool
from .utils import estimate_token_count
from core.logger import UnifiedLogger
from core.constants import WEB_TOOL_SECURITY_NOTICE
from core.settings import get_default_api_timeout, get_web_tool_max_tokens
from core.settings.secrets_store import get_secret_value

logger = UnifiedLogger(tag="tavily-extract")


class TavilyExtract(BaseTool):
    """Tavily Extract tool for content extraction from specific URLs."""
    
    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for URL content extraction."""
        tavily_api_key = get_secret_value('TAVILY_API_KEY')
        if not tavily_api_key:
            raise ValueError("Secret 'TAVILY_API_KEY' is required for TavilyExtract.")
        
        client = TavilyClient(api_key=tavily_api_key)
        
        async def tavily_extract(
            *,
            urls: Union[str, List[str]],
            extract_depth: Literal['basic', 'advanced'] = 'basic',
            include_images: bool = False
        ) -> str:
            """Extract content from specific URLs using Tavily.

            Perfect for extracting documentation, articles, or specific web pages.
            Returns clean, structured content from the provided URLs.

            Args:
                urls: Single URL string or list of URLs to extract content from
                extract_depth: 'basic' for quick extraction, 'advanced' for comprehensive
                include_images: Whether to include images in results

            Returns:
                Extracted content as formatted text
            """
            logger.set_sinks(["validation"]).info(
                "tool_invoked",
                data={"tool": "tavily_extract"},
            )
            # Tavily API has max 120 second timeout, use min of our default and 120
            timeout = min(int(get_default_api_timeout()), 120)
            
            try:
                result = client.extract(
                    urls=urls,
                    format='markdown',
                    extract_depth=extract_depth,
                    include_images=include_images,
                    timeout=timeout
                )
            except Exception as exc:
                return f"Tavily extract error: {exc}"
            
            if not result.get('results'):
                return f"No content could be extracted from: {urls}"
            
            # Format the results
            extracted_content = []
            
            for item in result['results']:
                url = item.get('url', 'Unknown URL')
                content = item.get('raw_content', '')
                
                if content:
                    extracted_content.append(f"# Content from {url}\n\n{content}")
                else:
                    extracted_content.append(f"# Failed to extract content from {url}")
            
            # Include failed results if any
            if result.get('failed_results'):
                failed_urls = [item.get('url', 'Unknown URL') for item in result['failed_results']]
                extracted_content.append("\n## Failed to extract from:\n" + "\n".join(f"- {url}" for url in failed_urls))

            # Format final content
            final_content = "\n\n".join(extracted_content)

            # Check token count to prevent context window overflow
            token_count = estimate_token_count(final_content)
            max_tokens = get_web_tool_max_tokens()

            if max_tokens > 0 and token_count > max_tokens:
                # Format URLs for display
                url_list = urls if isinstance(urls, list) else [urls]
                url_display = "\n".join(f"  - {u}" for u in url_list)

                return f"""❌ Extraction Error: Content exceeds context window limit

The extracted content from the requested URL(s) is too large to process:
  - Extracted: {token_count:,} tokens
  - Maximum: {max_tokens:,} tokens
  - Size: {len(final_content):,} characters

URLs attempted:
{url_display}

This typically happens with:
  - Encyclopedia/Wikipedia articles (extensive citations and navigation)
  - Documentation sites with large navigation trees
  - Pages with many embedded links and references

Please inform the user that this URL cannot be extracted due to size constraints.

Suggested alternatives:
  1. Use web_search to get summarized information about the topic instead
  2. Try extracting a more specific sub-page or section if available
  3. Use tavily_crawl to explore related pages with smaller individual content
  4. Ask the user to provide a different, more focused URL
  5. Route tool output to a buffer (e.g. @tools tavily_extract(output=variable: web_buffer)) and explore it with buffer_ops"""

            return final_content
        
        return Tool(
            tavily_extract,
            name='tavily_extract',
            description='Extract content from specific URLs using Tavily for documentation, articles, or web pages.'
        )
    
    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for Tavily Extract."""
        return """URL Content Extraction: Use when you need to extract full content from specific web pages, documentation, articles, or blog posts. Perfect for:
- Extracting documentation from specific pages
- Getting full article content for analysis
- Pulling content from multiple related URLs
- Converting web pages to clean markdown for processing

OPERATE CONSERVATIVELY:
- Start with a single URL and the 'basic' extract depth; review the output before requesting more.
- If you need additional sections, run a second extract on the next specific URL or switch to 'advanced' only after confirming scope.
- Avoid batching many URLs at once—break large jobs into multiple extract calls to prevent oversized responses.

Always specify the exact URL(s) you want to extract content from.
Example: tavily_extract(urls="https://example.com/docs", extract_depth="basic").
Always use named parameters.
You may route output with output="variable:NAME" or output="file:PATH" and optional write_mode=append|replace|new.
output must be a string (no JSON objects or dicts).""" + WEB_TOOL_SECURITY_NOTICE
