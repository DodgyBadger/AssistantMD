# `web_search_tavily`

## Purpose

Search the web with Tavily when you want higher-quality research-oriented results.

## When To Use

- you need web search with stronger research focus
- you are gathering leads before extracting specific pages
- you want better starting material for multi-step research

## When Not To Use

- you already know the URL and should use `tavily_extract`
- a lightweight search is sufficient

## Arguments

- `query`: required search query

## Examples

```python
web_search_tavily(query="latest fastapi release")
```

## Output Shape

Returns plain text containing a small set of results with:

- title
- snippet
- URL

## Notes

- use this to find promising URLs first
- once you know the exact page, prefer `tavily_extract`
