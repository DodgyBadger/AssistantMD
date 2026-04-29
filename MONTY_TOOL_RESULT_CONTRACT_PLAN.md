# Monty Tool Result Contract Refactor

## Goal

Align direct tool results in Monty scripts with Pydantic AI's `ToolReturn` shape as closely as possible, so authoring agents do not need to learn a separate AssistantMD-specific tool-result contract.

## Target Contract

Direct tool calls in Monty return a lightweight wrapper with:

- `return_value`: canonical Pydantic `ToolReturn.return_value`
- `content`: canonical Pydantic `ToolReturn.content`, used only for optional extra user content outside the tool result
- `metadata`: canonical Pydantic `ToolReturn.metadata`, plus wrapper metadata such as `tool_name` and `return_type`
- `items`: AssistantMD projection for helper composition, not part of Pydantic AI

Remove top-level wrapper fields:

- `output`
- `status`
- `name`

Tool status and identity should be read from metadata:

```python
result.metadata["status"]
result.metadata["tool_name"]
```

## File Ops Contract

Refactor `file_ops_safe` successful read-like operations so `return_value` is the payload the caller asked for, not a status-prefixed message.

- `read` markdown: clean file text in `return_value`
- `read` virtual markdown: clean file text in `return_value`
- `read` markdown with skipped image attachments: normalized markdown/text fallback in `return_value`
- `head`: selected file text in `return_value`
- `read` image: multimodal payload in `return_value`
- `read` markdown with attached images: interleaved multimodal payload in `return_value`
- mutation operations (`write`, `append`, `mkdir`, `move`) keep concise success/error messages in `return_value`
- listing/search/frontmatter can keep current human-readable result text in `return_value` unless a better structured payload is introduced later
- `content` stays `None` unless a tool intentionally needs to send extra side-loaded user content outside the tool result

Metadata remains the place for status, operation, counts, paths, sizes, diagnostics, and attachment details.

## Implementation Steps

1. Update `ScriptToolResult` in `core/authoring/contracts.py`.
   - Replace `name`, `status`, and `output` with `return_value`.
   - Keep `content`, `metadata`, and `items`.

2. Update `normalize_tool_result(...)` in `core/authoring/helpers/runtime_common.py`.
   - Populate `return_value` from Pydantic `ToolReturn.return_value`.
   - Always inject `metadata["tool_name"]`.
   - Preserve `metadata["return_type"]` and `metadata["has_content"]`.
   - Update item projection to use `return_value` rather than `output`.

3. Update Monty direct-tool logging in `core/authoring/runtime/monty_runner.py`.
   - Log `return_value_chars`.
   - Read status from `tool_result.metadata.get("status")`.

4. Refactor `core/tools/file_ops_safe.py`.
   - For successful text reads and `head`, return clean payloads.
   - Keep errors and mutation acknowledgements as concise messages.
   - Move successful multimodal read payloads into `return_value`.
   - Use `content` only for deliberate extra side-loaded user content.

5. Update first-party scripts under `data/PersonalVault/AssistantMD/Authoring/` and seed templates.
   - Replace `.output` with `.return_value`.
   - Remove header-stripping helpers where reads now return clean text.
   - Replace `.status` and `.name` with metadata access if present.

6. Update validation scenarios.
   - Replace `.output` assertions/usages with `.return_value`.
   - Add focused assertions:
     - markdown read returns clean `return_value`
     - markdown read has `content is None`
     - image read has multimodal `return_value` and `content is None`
     - markdown-with-images read has interleaved multimodal `return_value` and `content is None`
     - `metadata["status"]` remains available
     - `items[0].content` still projects clean file content

7. Update docs.
   - `docs/tools/code_execution.md`
   - `docs/tools/file_ops_safe.md`
   - `docs/tools/delegate.md`
   - `docs/use/authoring.md`
   - architecture docs if needed

## Validation Plan

Run targeted local checks:

- `python -m py_compile` on changed Python files.
- Existing integration scenario for code execution.
- Existing integration scenario for authoring contract.
- Existing integration scenario for delegate tool.
- Add or update a scenario assertion covering `file_ops_safe(read)` direct-tool return shape.

Maintainers still own full validation suite execution.

## Implementation Status

Implemented in this branch.

- Direct Monty tool results expose `return_value`, `metadata`, `content`, and `items`; top-level `output`, `status`, and `name` were removed.
- Bound tools are normalized to a `ToolReturn` envelope at the shared tool-binding layer, so tools that naturally return plain strings or dicts still present the same Monty-facing contract.
- `file_ops_safe(read)` and `head` now return clean payloads in `return_value`.
- Image reads and markdown-with-image reads now return multimodal payloads in `return_value` with `content is None`.
- First-party authoring scripts, seed templates, tool docs, and validation scripts now use `.return_value`.
- Chat tool overflow handling now detects multimodal payloads in either `ToolReturn.return_value` or `ToolReturn.content`.

Targeted checks run:

- `python -m py_compile` on changed Python files.
- `python validation/run_validation.py run integration/core/authoring_contract`
- `python validation/run_validation.py run integration/core/code_execution`
- `python validation/run_validation.py run integration/core/delegate_tool`
- `python validation/run_validation.py run integration/basic_haiku_workflow integration/basic_haiku_context integration/core/chat_cache_multi_pass`
- One-off direct Monty smokes for plain markdown and image `file_ops_safe(read)` return shape.

## Risks

- This is a deliberate breaking change for current authored scripts.
- Chat tool behavior must not regress; Pydantic AI still receives `return_value` as the formal tool return.
- Multimodal `return_value` through the current chat provider path must be validated before removing the old side-loaded payload behavior.
- Some tests/scripts currently strip status headers from `.output`; those must be updated together with `file_ops_safe(read)`.
- `items` remains AssistantMD-specific and should be documented as a projection, not Pydantic AI canon.
