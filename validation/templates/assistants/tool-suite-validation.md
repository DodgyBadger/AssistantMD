---
workflow: step
enabled: false
description: Validation assistant that exercises every available tool with the TestModel.
---

## STEP1_DOCUMENTATION
@model test
@tools documentation_access
@output-file tool-outputs/documentation-access

Provide a quick summary of the documentation home page using the documentation access tool.

## STEP2_FILE_OPS_SAFE
@model test
@tools file_ops_safe
@output-file tool-outputs/file-ops-safe

Call the safe file operations tool with any operation so we capture the tool output.

## STEP3_FILE_OPS_UNSAFE
@model test
@tools file_ops_unsafe
@output-file tool-outputs/file-ops-unsafe

Invoke the unsafe file operations tool once to record its response. Do not rely on any existing files.

## STEP4_WEB_SEARCH_DUCKDUCKGO
@model test
@tools web_search_duckduckgo
@output-file tool-outputs/web-search-duckduckgo

Use the DuckDuckGo search backend to look up a topic of your choice.

## STEP5_WEB_SEARCH_TAVILY
@model test
@tools web_search_tavily
@output-file tool-outputs/web-search-tavily

Use the Tavily search backend to look up a topic of your choice.

## STEP6_TAVILY_EXTRACT
@model test
@tools tavily_extract
@output-file tool-outputs/tavily-extract

Call the Tavily extract tool on any URL so we capture the tool output.

## STEP7_TAVILY_CRAWL
@model test
@tools tavily_crawl
@output-file tool-outputs/tavily-crawl

Call the Tavily crawl tool on any URL so we capture the tool output.

## STEP8_CODE_EXECUTION
@model test
@tools code_execution
@output-file tool-outputs/code-execution

Run the code execution tool with a short code sample so we capture the tool output.
