# `browser`

## Purpose

Open a page in a headless browser and extract compact content from the main page region.

## When To Use

- the page is JavaScript-heavy
- `tavily_extract` failed
- `tavily_extract` returned thin or incomplete content
- you need a targeted selector-based extraction

## When Not To Use

- you do not know the URL yet
- a search tool would answer the question faster
- `tavily_extract` is likely sufficient
- you need broad exploratory browsing across many pages

## Arguments

- `url`: required page URL
- `goal`: optional short extraction goal
- `wait_until`: one of `load`, `domcontentloaded`, `networkidle`
- `wait_for_selector`: optional selector to wait for after navigation
- `extract_selector`: optional selector to extract instead of the inferred main region
- `include_links`: optional boolean to include a short link list

## Examples

```python
browser(url="https://example.com/docs")
```

```python
browser(
    url="https://example.com/app",
    wait_for_selector="main",
)
```

```python
browser(
    url="https://example.com/help",
    extract_selector="article",
    include_links=True,
)
```

## Output Shape

Returns compact markdown text with:

- requested URL
- final URL
- page title
- extracted selector
- status code
- extracted content
- optional short links section

## Notes

- prefer one exact URL per call
- avoid repeated selector guesses
- downloads, local targets, and non-read HTTP methods are blocked
- browser state is isolated per call
