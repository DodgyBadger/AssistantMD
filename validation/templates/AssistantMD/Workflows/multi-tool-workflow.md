---
schedule: once: 2030-01-01 09:00
workflow_engine: step
enabled: true
description: Multi-tool testing workflow that validates all tool backends
---

## INSTRUCTIONS
You are a testing workflow that validates different tool capabilities. Each step tests a specific tool independently.

## STEP1_WEB_SEARCH_DUCKDUCKGO
@model haiku
@tools web_search_duckduckgo
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output-file tools/duckduckgo-test

Use the DuckDuckGo search tool to find information about "Python programming basics" and provide a brief summary.

## STEP2_WEB_SEARCH_TAVILY
@model haiku
@tools web_search_tavily
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output-file tools/tavily-test

Use the Tavily search tool to find information about "machine learning fundamentals" and provide a brief summary.

## STEP3_CODE_EXECUTION_LIBRECHAT
@model haiku
@tools code_execution_librechat
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output-file tools/librechat-test

Use the LibreChat code execution tool to create a simple Python list [1, 2, 3, 4, 5] and find its length.

## STEP4_WEB_SEARCH_GENERIC
@model haiku
@tools web_search
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output-file tools/web-search-generic-test

Use the generic web search tool to find information about "JavaScript basics" and provide a brief summary.

## STEP5_CODE_EXECUTION_GENERIC
@model haiku
@tools code_execution
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output-file tools/code-execution-generic-test

Use the generic code execution tool to calculate 7 * 8 and show the result.

## STEP6_TAVILY_EXTRACT
@model haiku
@tools tavily_extract
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output-file tools/tavily-extract-test

Use the Tavily extract tool to extract content from https://docs.python.org/3/tutorial/introduction.html and provide a summary of the Python introduction.

## STEP7_TAVILY_CRAWL
@model haiku
@tools tavily_crawl
@run-on monday, tuesday, wednesday, thursday, friday, saturday, sunday
@output-file tools/tavily-crawl-test

Use the Tavily crawl tool to crawl content from https://www.python.org and provide a summary of what you find on the Python website.
