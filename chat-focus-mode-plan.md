# Chat Focus Mode Plan

## Scope

Add an optional chat focus mode that lets the chat transcript and prompt editor take over the browser viewport, with a draggable divider between the message area and the composer.

## User-Visible Contract

- A focus-mode control is available from the chat UI.
- Entering focus mode hides the top tabs and chat settings.
- The chat message area and prompt composer fill the viewport.
- A horizontal divider between messages and composer can be dragged with mouse or touch/pointer input.
- Exiting focus mode restores the regular chat layout.
- The last composer height is remembered locally for the browser.

## Affected Areas

- `static/index.html`: chat markup and inline CSS for focus layout and splitter.
- `static/app.js`: focus-mode toggle, splitter pointer handling, persistence, and Escape handling.

## Validation Target

Run targeted local checks:

- `node --check static/app.js`
- Browser smoke test at desktop and mobile widths:
  - focus button enters and exits mode
  - tabs/settings hide in focus mode
  - splitter resizes messages/composer without overflow
  - send and attachment controls still work structurally

## Next Step

Implement the smallest usable focus mode with clamped splitter sizing and localStorage persistence.
