# Multimodal Architecture

This document describes how AssistantMD handles image inputs alongside markdown text. The user-facing model is simple: markdown files can reference images in the vault, and the system will attach or reference those images according to policy and model capabilities.

## Scope

- Local image inputs via `@input file:...`
- Embedded image refs inside markdown
- Tool path for `file_ops_safe(read)` on images and markdown with embedded images
- Attachment and safety policies for image payloads

## Key Components

- `core/chunking/markdown.py`: parses markdown into ordered text and image-ref chunks.
- `core/chunking/prompt_builder.py`: assembles prompts with interleaved text/image parts.
- `core/chunking/image_refs.py`: resolves embedded image refs and normalizes refs for fallback.
- `core/utils/image_inputs.py`: shared attachment gating and marker formatting.
- `core/tools/file_ops_safe.py`: image-aware read path for chat tool calls.
- `core/llm/model_utils.py`: `vision` capability checks for model aliases.

## Data Flow Overview

### Workflow + Context `@input`

1. `@input` directives resolve files in the vault (`core/directives/input.py`).
2. `build_input_files_prompt(...)` builds the ordered prompt payload.
3. For markdown with embedded images:
   - parse into ordered chunks
   - resolve local image refs relative to the markdown file
   - attach images when policy allows
4. For direct image inputs (`@input file: image.jpg`):
   - attach the image directly when policy allows
5. If the selected model lacks `vision`, image attachments are replaced with refs.

### `file_ops_safe(read)`

- Reading a local image returns a multimodal `ToolReturn` (text note + image attachment).
- Reading markdown with embedded images uses the same chunking + attachment logic as `@input`.
- If the markdown is too large, image attachments are skipped and refs are normalized.

## Attachment Policy (Images)

The shared attachment policy applies consistently across workflows, context templates, and tool reads.

Policy gates (all must pass to attach images):
- Text token preflight: skip attachments if raw markdown text exceeds `auto_buffer_max_tokens`.
- Max image count
- Max per-image size
- Max total bytes
- Model capability: requires `vision`

If any gate fails, images are not attached; image references are normalized so they remain followable.

## Auto-Buffering + Large Inputs

When a markdown input is too large, the system normalizes embedded image refs to vault-relative paths and returns text-only content. This enables auto-buffering to protect the context window while preserving image discoverability.

## Marker Conventions

When images cannot be attached or are missing, the prompt contains explicit markers:

- `[IMAGE: path]` (attached image)
- `[IMAGE REF: path]` (reference only)
- `[REMOTE IMAGE REF: url]` (remote URL)
- `[MISSING IMAGE: ref]` (unresolvable ref)

These markers are defined centrally in `core/utils/image_inputs.py`.

## Security Notes

Image files are treated as untrusted content. Resolution always enforces vault boundaries and attachment policy limits. Remote image URLs remain references by default (no automatic download/attach).
