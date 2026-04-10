# `tavily_extract`

## Purpose

Extract full content from specific web pages, articles, and documentation URLs.

## When To Use

- you already know the exact URL
- you want page content without a full browser session
- you need a better first pass than raw search snippets

## When Not To Use

- you do not know the URL yet
- you need broad multi-page coverage
- the site is clearly JavaScript-heavy and extract keeps returning thin content

## Arguments

- `urls`: one URL or a list of URLs
- `extract_depth`: `basic` or `advanced`
- `include_images`: whether to include images in results

## Examples

```python
tavily_extract(
    urls="https://example.com/docs",
    extract_depth="basic",
)
```

```python
tavily_extract(
    urls=[
        "https://example.com/docs/a",
        "https://example.com/docs/b",
    ],
    extract_depth="advanced",
)
```

## Output Shape

Returns markdown-style text grouped by URL, plus a failed-results section when relevant.

## Notes

- prefer this before `browser` when the URL is known
- start with one URL and `basic`
- avoid large URL batches on the first pass
- if this returns thin content, `browser` may be the better fallback
