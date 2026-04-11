# `web_search_duckduckgo`

## Purpose

Search the web with DuckDuckGo for lightweight general-purpose results.

## When To Use

- you need a simple web search
- you want a lightweight first pass
- premium Tavily search is unavailable or unnecessary

## Arguments

- `query`: required search query

## Examples

```python
web_search_duckduckgo(query="latest postgres release notes")
```

## Output Shape

Returns plain text containing up to a few search hits with:

- title
- snippet
- URL

## Notes

- use this for lightweight discovery
- once you know a promising URL, switch to `tavily_extract` or `browser`
