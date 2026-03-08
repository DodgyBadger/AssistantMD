"""
Browser tool backed by Playwright for resilient page extraction.

Provides conservative browser-driven extraction for pages where simple crawlers
or extract APIs fail, especially on JavaScript-heavy sites.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

from markdownify import markdownify as html_to_markdown
from pydantic_ai.tools import Tool

from core.constants import WEB_TOOL_SECURITY_NOTICE
from core.logger import UnifiedLogger
from core.settings import get_default_api_timeout
from .base import BaseTool


logger = UnifiedLogger(tag="browser-tool")


class BrowserTool(BaseTool):
    """Playwright-backed browser tool for targeted extraction."""

    _MAX_LINKS = 20
    _MAX_NAVIGATION_TIMEOUT_MS = 20_000
    _MAX_SELECTOR_TIMEOUT_MS = 4_000
    _ROOT_SELECTORS = ("main", "article", "[role='main']", "body")
    _FALLBACK_CANDIDATE_SELECTORS = ("section", "div", "article", "main", "table", "td")
    _VALID_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle"}
    _BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Get the Playwright-backed browser tool."""

        async def browser(
            *,
            url: str,
            goal: str = "",
            wait_until: str = "domcontentloaded",
            wait_for_selector: str = "",
            extract_selector: str = "",
            include_links: bool = False,
        ) -> str:
            """Open a page in a headless browser and extract compact page content.

            :param url: Page URL to open
            :param goal: Brief extraction goal to guide target selection
            :param wait_until: Navigation readiness event
            :param wait_for_selector: Optional selector to wait for after navigation
            :param extract_selector: Optional selector to extract instead of the main content area
            :param include_links: Include a short list of visible links from the extracted region
            """
            logger.set_sinks(["validation"]).info(
                "tool_invoked",
                data={"tool": "browser"},
            )

            try:
                return await cls._browse(
                    url=url,
                    goal=goal,
                    wait_until=wait_until,
                    wait_for_selector=wait_for_selector,
                    extract_selector=extract_selector,
                    include_links=include_links,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.set_sinks(["validation"]).info(
                    "browser_navigation_failed",
                    data={
                        "tool": "browser",
                        "url": url,
                        "error": str(exc),
                    },
                )
                return f"Browser error: {exc}"

        return Tool(
            browser,
            name="browser",
            description=(
                "Open a web page in a headless browser and extract compact content "
                "from the main page region."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for the browser tool."""
        return """
## browser usage instructions

Use when you need a real browser to load and extract content from a known URL,
especially after simple extraction fails or when the site depends on JavaScript.

Prefer this escalation ladder:
- Search tools when you do not know the URL yet
- `tavily_extract` first when you know the URL and only need page content
- `browser` when Tavily fails, returns thin content, or the page is clearly JS-heavy

Operate conservatively:
- Start with one exact URL
- On the first call, do not guess `wait_for_selector` or `extract_selector` unless the user provided one
- Avoid broad browsing or exploratory navigation unless the user explicitly wants it
- Use `extract_selector` only after a first pass tells you the page structure
- Use `wait_for_selector` only when the page clearly loads content asynchronously
- Set `include_links=True` only when links are important to the task

Failure handling:
- If the tool says the URL starts a download, switch to a different page URL; selector retries will not help
- If the tool says your selector was not found, retry without selectors or with one of the suggested candidate roots
- Prefer one clean retry over repeated selector guesses

Examples:
- browser(url="https://example.com/docs")
- browser(url="https://example.com/app", wait_for_selector="main")
- browser(url="https://example.com/help", extract_selector="article", include_links=True)
""" + WEB_TOOL_SECURITY_NOTICE

    @classmethod
    async def _browse(
        cls,
        *,
        url: str,
        goal: str,
        wait_until: str,
        wait_for_selector: str,
        extract_selector: str,
        include_links: bool,
    ) -> str:
        cls._validate_url(url)
        normalized_wait_until = cls._validate_wait_until(wait_until)

        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Add the `playwright` package and run "
                "`playwright install chromium` on the host."
            ) from exc

        timeout_ms = min(
            max(int(get_default_api_timeout() * 1000), 1_000),
            cls._MAX_NAVIGATION_TIMEOUT_MS,
        )
        final_url = url
        status_code: int | None = None

        try:
            async with async_playwright() as playwright:
                browser_instance = await playwright.chromium.launch(headless=True)
                context = None
                try:
                    context = await browser_instance.new_context(accept_downloads=False)
                    page = await context.new_page()
                    page.set_default_timeout(timeout_ms)
                    await page.route("**/*", cls._route_request)
                    response = await page.goto(
                        url,
                        wait_until=normalized_wait_until,
                        timeout=timeout_ms,
                    )
                    if wait_for_selector.strip():
                        await cls._wait_for_selector(
                            page=page,
                            selector=wait_for_selector.strip(),
                            timeout_ms=min(timeout_ms, cls._MAX_SELECTOR_TIMEOUT_MS),
                        )

                    if extract_selector.strip():
                        target_selector = extract_selector.strip()
                        await cls._ensure_selector_present(
                            page=page,
                            selector=target_selector,
                        )
                        locator = page.locator(target_selector).first
                    else:
                        locator, target_selector = await cls._resolve_best_root(page)
                    title = (await page.title()).strip()
                    extracted = await cls._extract_region(
                        locator=locator,
                        include_links=include_links,
                    )
                    final_url = page.url
                    status_code = response.status if response else None
                finally:
                    if context is not None:
                        await context.close()
                    await browser_instance.close()
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"navigation timed out after {timeout_ms} ms") from exc
        except PlaywrightError as exc:
            if "Download is starting" in str(exc):
                raise RuntimeError(
                    "URL initiates a download instead of rendering an HTML page. "
                    "Try a different document URL; selector retries will not help."
                ) from exc
            raise RuntimeError(str(exc)) from exc

        logger.set_sinks(["validation"]).info(
            "browser_navigation_succeeded",
            data={
                "tool": "browser",
                "url": url,
                "final_url": final_url,
                "status_code": status_code,
            },
        )
        logger.set_sinks(["validation"]).info(
            "browser_extraction_succeeded",
            data={
                "tool": "browser",
                "url": url,
                "selector": target_selector,
                "title": title,
                "include_links": include_links,
            },
        )

        return cls._format_result(
            url=url,
            final_url=final_url,
            status_code=status_code,
            title=title,
            selector=target_selector,
            goal=goal,
            content=extracted["content"],
            links=extracted["links"],
        )

    @classmethod
    async def _resolve_root_selector(cls, page: Any) -> str:
        """Return the first content root selector that exists on the page."""
        for selector in cls._ROOT_SELECTORS:
            if await page.locator(selector).count():
                return selector
        return "body"

    @classmethod
    async def _resolve_best_root(cls, page: Any) -> tuple[Any, str]:
        """Choose the best extraction root using semantic selectors first, then a content heuristic."""
        for selector in cls._ROOT_SELECTORS[:-1]:
            locator = page.locator(selector).first
            if await locator.count():
                return locator, selector

        best_handle = await page.evaluate_handle(
            """(candidateSelectors) => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style) return true;
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };

                const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
                const seen = new Set();
                let best = null;

                for (const selector of candidateSelectors) {
                    const elements = document.querySelectorAll(selector);
                    for (const el of elements) {
                        if (seen.has(el) || !isVisible(el)) continue;
                        seen.add(el);

                        const text = normalize(el.innerText || '');
                        if (text.length < 400) continue;

                        const links = el.querySelectorAll('a[href]').length;
                        const paras = el.querySelectorAll('p').length;
                        const headings = el.querySelectorAll('h1,h2,h3,h4,h5,h6').length;
                        const controls = el.querySelectorAll('button,input,select,textarea').length;
                        const idClass = `${el.id || ''} ${typeof el.className === 'string' ? el.className : ''}`.toLowerCase();
                        const textNodes = Math.max(text.length / 80, 1);
                        const linkDensity = links / textNodes;

                        let score = text.length;
                        score += paras * 180;
                        score += headings * 220;
                        score -= links * 18;
                        score -= controls * 120;
                        score -= linkDensity * 900;
                        score -= Math.max(0, links - 80) * 45;
                        score -= Math.max(0, headings - 40) * 35;

                        if (paras === 0 && links > 50) score -= 3000;

                        if (el.tagName === 'ARTICLE' || el.tagName === 'MAIN') score += 800;
                        if (idClass.includes('content')) score += 500;
                        if (idClass.includes('article')) score += 400;
                        if (idClass.includes('section')) score += 250;

                        if (
                            idClass.includes('nav') ||
                            idClass.includes('menu') ||
                            idClass.includes('sidebar') ||
                            idClass.includes('search') ||
                            idClass.includes('toolbar') ||
                            idClass.includes('breadcrumb') ||
                            idClass.includes('footer') ||
                            idClass.includes('header') ||
                            idClass.includes('toc') ||
                            idClass.includes('contents')
                        ) {
                            score -= 2200;
                        }

                        if (!best || score > best.score) {
                            best = { element: el, score };
                        }
                    }
                }

                return best ? best.element : document.body;
            }""",
            list(cls._FALLBACK_CANDIDATE_SELECTORS),
        )
        locator = page.locator("body")
        target_selector = "body"
        locator = best_handle.as_element()
        if locator is None:
            await best_handle.dispose()
            return page.locator("body").first, "body"
        element_locator = locator
        tag_name = (
            await element_locator.evaluate("(node) => node.tagName.toLowerCase()")
        ).strip()
        element_id = (
            await element_locator.evaluate("(node) => node.id || ''")
        ).strip()
        class_name = (
            await element_locator.evaluate(
                "(node) => typeof node.className === 'string' ? node.className : ''"
            )
        ).strip()
        target_selector = cls._describe_element_selector(tag_name, element_id, class_name)
        return element_locator, target_selector

    @classmethod
    async def _extract_region(cls, *, locator: Any, include_links: bool) -> dict[str, Any]:
        """Extract compact content and optional links from a selected page region."""
        payload = await locator.evaluate(
            """(node, includeLinks) => {
                const clone = node.cloneNode(true);
                clone.querySelectorAll('script,style,noscript,template').forEach(
                    (element) => element.remove()
                );
                const html = clone.innerHTML || '';
                const links = includeLinks
                    ? Array.from(clone.querySelectorAll('a[href]'))
                        .slice(0, 20)
                        .map((anchor) => ({
                            text: (anchor.innerText || anchor.textContent || '').trim(),
                            href: anchor.href || anchor.getAttribute('href') || '',
                        }))
                        .filter((item) => item.href)
                    : [];
                return { html, links };
            }""",
            include_links,
        )
        markdown = html_to_markdown(str(payload.get("html", "")).strip(), heading_style="ATX")
        content = cls._clean_extracted_text(markdown)
        links = cls._format_links(payload.get("links", [])) if include_links else []
        if not content:
            content = "*No extractable content found in the selected region.*"
        return {"content": content, "links": links}

    @classmethod
    def _clean_extracted_text(cls, text: str) -> str:
        """Normalize extracted text for compact tool output."""
        compact = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        while "\n\n\n" in compact:
            compact = compact.replace("\n\n\n", "\n\n")
        return compact

    @classmethod
    def _format_links(cls, raw_links: list[dict[str, Any]]) -> list[str]:
        """Format extracted links into a compact markdown list."""
        lines: list[str] = []
        for item in raw_links[: cls._MAX_LINKS]:
            href = str(item.get("href", "")).strip()
            if not href:
                continue
            text = str(item.get("text", "")).strip() or href
            lines.append(f"- [{text}]({href})")
        return lines

    @classmethod
    def _format_result(
        cls,
        *,
        url: str,
        final_url: str,
        status_code: int | None,
        title: str,
        selector: str,
        goal: str,
        content: str,
        links: list[str],
    ) -> str:
        """Render extracted browser output as compact markdown."""
        lines = [
            "# Browser Extraction",
            "",
            f"- Requested URL: {url}",
            f"- Final URL: {final_url}",
            f"- Page title: {title or '(untitled)'}",
            f"- Extracted selector: {selector}",
            f"- HTTP status: {status_code if status_code is not None else 'N/A'}",
        ]
        if goal.strip():
            lines.append(f"- Goal: {goal.strip()}")

        lines.extend(["", "## Content", "", content])
        if links:
            lines.extend(["", "## Links", ""])
            lines.extend(links)
        return "\n".join(lines)

    @classmethod
    async def _route_request(cls, route: Any) -> None:
        """Abort non-essential asset requests to keep extraction fast."""
        if route.request.resource_type in cls._BLOCKED_RESOURCE_TYPES:
            await route.abort()
            return
        await route.continue_()

    @classmethod
    async def _wait_for_selector(
        cls,
        *,
        page: Any,
        selector: str,
        timeout_ms: int,
    ) -> None:
        """Wait briefly for a requested selector and fail with guidance if absent."""
        try:
            await page.wait_for_selector(selector, timeout=timeout_ms)
        except Exception as exc:
            candidates = await cls._candidate_root_selectors(page)
            candidate_text = ", ".join(candidates) if candidates else "body"
            raise RuntimeError(
                f"Requested wait_for_selector '{selector}' was not found. "
                f"Retry without selectors or use one of: {candidate_text}."
            ) from exc

    @classmethod
    async def _ensure_selector_present(
        cls,
        *,
        page: Any,
        selector: str,
    ) -> None:
        """Verify an explicit extraction selector exists before evaluating it."""
        try:
            if await page.locator(selector).count():
                return
        except Exception as exc:
            candidates = await cls._candidate_root_selectors(page)
            candidate_text = ", ".join(candidates) if candidates else "body"
            raise RuntimeError(
                f"Requested extract_selector '{selector}' was not found. "
                f"Retry without selectors or use one of: {candidate_text}."
            ) from exc
        candidates = await cls._candidate_root_selectors(page)
        candidate_text = ", ".join(candidates) if candidates else "body"
        raise RuntimeError(
            f"Requested extract_selector '{selector}' was not found. "
            f"Retry without selectors or use one of: {candidate_text}."
        )

    @classmethod
    async def _candidate_root_selectors(cls, page: Any) -> list[str]:
        """Return simple candidate root selectors present on the page."""
        candidates: list[str] = []
        for selector in cls._ROOT_SELECTORS:
            if await page.locator(selector).count():
                candidates.append(selector)
        return candidates or ["body"]

    @staticmethod
    def _describe_element_selector(tag_name: str, element_id: str, class_name: str) -> str:
        """Build a human-readable selector label for logging and output."""
        if element_id:
            return f"{tag_name}#{element_id}"
        classes = [item for item in class_name.split() if item]
        if classes:
            return f"{tag_name}.{'.'.join(classes[:3])}"
        return tag_name

    @classmethod
    def _validate_wait_until(cls, wait_until: str) -> str:
        """Validate the requested Playwright navigation readiness state."""
        normalized = (wait_until or "").strip().lower() or "domcontentloaded"
        if normalized not in cls._VALID_WAIT_UNTIL:
            allowed = ", ".join(sorted(cls._VALID_WAIT_UNTIL))
            raise ValueError(f"wait_until must be one of: {allowed}")
        return normalized

    @staticmethod
    def _validate_url(url: str) -> None:
        """Reject non-web schemes and obvious local-network targets."""
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https", "data"}:
            raise ValueError("Only http, https, and data URLs are supported")
        if parsed.scheme == "data":
            return

        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            raise ValueError("URL must include a hostname")
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
            ".local"
        ):
            raise ValueError("Local network targets are not allowed")

        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return

        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise ValueError("Private or local network targets are not allowed")
