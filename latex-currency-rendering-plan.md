# LaTeX Currency Rendering Plan

## Scope

Prevent ordinary currency ranges such as `$10K-$20k` from being rendered as MathJax in assistant chat messages while preserving intentional LaTeX rendering.

## Current Findings

- Chat assistant content is rendered in `static/app.js` by `renderAssistantHtml`.
- Markdown is parsed with `marked`, sanitized with `DOMPurify`, then post-processed by MathJax through `renderAssistantMath`.
- `protectLatexForMarkdown` only protects LaTeX-like spans from Markdown parsing. It restores the raw dollar delimiters before MathJax scans the DOM.
- `static/index.html` configures MathJax with single-dollar inline math delimiters: `inlineMath: [['$', '$'], ['\\(', '\\)']]`.
- The local regex avoids treating `$` followed by a digit as a protected LaTeX segment, but MathJax still sees the final DOM text and can interpret dollar pairs itself.

## Proposed Fix

Remove single-dollar inline MathJax delimiters and keep explicit delimiters:

- inline: `\\(...\\)`
- display: `$$...$$` and `\\[...\\]`

Also remove single-dollar spans from the chat renderer's LaTeX protection pass so the renderer contract matches the MathJax contract.

## Affected Areas

- `static/index.html`: MathJax delimiter configuration.
- `static/app.js`: possible renderer helper changes if compatibility with single-dollar math is required.

## Validation Target

Add or run a targeted UI smoke check that verifies:

- `$10K-$20k` remains literal text in an assistant message.
- `\\(x + y\\)` renders as inline math.
- `$$x + y$$` or `\\[x + y\\]` renders as display math.
- Code spans and fenced code blocks are not processed as MathJax.

Maintainers should run the full validation suite if broader UI validation is desired.

## Next Step

Move to Testing and Validation with targeted syntax and renderer-regex smoke checks.
