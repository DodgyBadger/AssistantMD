# Chat No-Template And Context Error Plan

## Goal

Make unmanaged chat the default path and surface selected context template failures as explicit user-facing errors instead of silently bypassing context management.

## Implementation

1. Update the chat UI selector.
   - Add `No template` as the first option.
   - Make `No template` the default selection.
   - Keep real templates listed beneath it.

2. Update chat execution preflight.
   - Treat an empty or missing `context_template` as unmanaged chat.
   - Skip installing the history processor when no template is selected.

3. Harden selected-template failure handling.
   - Raise structured context-template execution errors for load, run, and result-shape failures.
   - Convert those failures into chat-facing API/SSE errors.
   - Do not silently fall back to another template or to unmanaged chat for the same turn.

4. Preserve observability.
   - Log template failure phase, template name, and template pointer server-side.
   - Keep existing successful context assembly logs intact.

## Validation

1. Verify the touched Python modules compile.
2. Verify the UI selector defaults to `No template`.
3. Verify selected-template failures produce explicit chat errors in both streaming and non-streaming paths.
