# `tavily_crawl`

## Purpose

Explore a website across multiple related pages when you need broader coverage than a single-page extract.

## When To Use

- you need structured multi-page coverage from one site
- you are exploring documentation or help-center sections
- you want a broader pass before targeted follow-up extracts

## When Not To Use

- you already know the exact page you need
- a single `tavily_extract` call is sufficient
- the site is heavily JavaScript-driven and crawling is likely to be thin

## Arguments

- `url`: required starting URL
- `instructions`: optional description of what content to find
- `max_depth`: crawl depth
- `max_breadth`: links to follow per page
- `limit`: max total pages
- `extract_depth`: `basic` or `advanced`
- `allow_external`: whether to follow external domains

## Examples

```python
tavily_crawl(
    url="https://example.com/docs",
    max_depth=1,
    max_breadth=3,
    limit=5,
)
```

## Output Shape

Returns markdown-style text with:

- base URL
- page count
- response time
- content per crawled page

## Notes

- start small
- keep `limit` low on the first pass
- if crawling returns only one page, the site may not be a good crawl candidate
- use targeted `tavily_extract` calls for pages you already know
