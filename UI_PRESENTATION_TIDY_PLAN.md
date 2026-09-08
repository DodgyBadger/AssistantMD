# UI Presentation Tidy Plan

## Scope

- Resolve `@` vault references whose filenames contain commas or nested extensionless path segments.
- Left-align wrapped live-link labels.
- Collapse Chat Settings options by default.
- Remove duplicate workflow-run failure summaries while preserving immediate execution results, durable history access, and workflow load errors.

## Affected Areas

- `static/js/file-references.js`
- `static/app.css`
- `static/js/session-controls.js`
- `static/js/dashboard-view.js`

## Validation

- Run JavaScript syntax checks for each changed script.
- Run focused source-level smoke checks for the agreed presentation contracts.
- Build the Tailwind stylesheet and confirm the working tree contains no unintended generated changes.

## Next Step

Request the maintainer-owned integration validation result before merge.
