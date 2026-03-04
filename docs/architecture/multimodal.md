# Multimodal Architecture

This document describes how AssistantMD handles image inputs alongside markdown text in workflow/context inputs and tool reads.

## Scope

- Direct image inputs via `@input file:...`
- Embedded image refs inside markdown inputs
- `file_ops_safe(read)` behavior for image and markdown-with-images reads
- Model capability gating and attachment/fallback policy

## Core Decisions

- `@input` image policy modes are `images=auto|ignore` only.
- Remote `http(s)` image refs are refs-only by default (no implicit download/attach).
- Text token protection and multimodal attachment limits are separate policy layers.
- `file_ops_safe` remains the primary read tool; no LLM-controlled per-call image-policy override.

## Key Components

- `core/chunking/markdown.py`: parses markdown into ordered text/image-ref chunks.
- `core/chunking/prompt_builder.py`: assembles interleaved prompt payloads.
- `core/chunking/image_refs.py`: resolves refs and applies normalized fallback markers.
- `core/utils/image_inputs.py`: shared marker formatting and image attachment helpers.
- `core/tools/file_ops_safe.py`: image-aware read path for tools.
- `core/llm/model_utils.py`: model `vision` capability checks.

## Data Flow

### Workflow/Context `@input`

1. `@input file:` resolves vault files (default `.md` only when no extension is provided).
2. Markdown inputs are parsed into ordered text/image chunks.
3. Direct image inputs and embedded local refs are attached only when policy + capability gates pass.
4. If attachment is not allowed, image refs are preserved as explicit markers.

### `file_ops_safe(read)`

- Reading an image returns multimodal `ToolReturn` content.
- Reading markdown-with-images uses the same chunking/policy pipeline as `@input`.
- For large markdown inputs or image-policy failures, output degrades to refs-normalized text.

## Capability + Policy Gates

Attachment requires all applicable gates to pass:

1. Model capability gate (`vision` required for image attachment)
2. Text token gate (`raw_text_tokens <= auto_buffer_max_tokens`)
3. Image preflight gates (count, per-image bytes, total image bytes)

Deterministic precedence:

1. token overflow gate
2. image preflight gate
3. multimodal attach

If any gate fails, the system returns followable refs markers instead of attachments.

## Auto-Buffering Interaction

Multimodal `ToolReturn` payloads are not routed through text token auto-buffer serialization. This avoids converting image payloads into large base64 text blobs that would incorrectly trigger buffering.

## Marker Conventions

Markers are centralized in `core/utils/image_inputs.py`.

- `[IMAGE: path]` (attached/local image marker)
- `[IMAGE REF: path]` (local ref-only fallback)
- `[REMOTE IMAGE REF: url]` (remote URL ref)
- `[MISSING IMAGE: ref]` (unresolvable ref)
- `[NON-IMAGE REF: path]` (resolved path not image-typed)

## Security Notes

- Image inputs are treated as untrusted content.
- Vault boundary checks apply to local path resolution.
- Remote URLs remain refs-only by default.
- Any future remote attach path requires explicit opt-in plus network/content limits.
