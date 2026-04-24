# Memory Service Plan

## Goal

Extract a shared conversation-history broker into `core/memory` so chat tools, authoring helpers, and future memory features reuse one fidelity-preserving source of truth.

## Immediate Slice

1. Add a memory service module under `core/memory`.
2. Move conversation-history source resolution, limit/filter handling, and normalization behind that service.
3. Rewire `memory_ops` to call the service instead of resolving providers directly.
4. Keep the external `memory_ops` tool contract stable for now.
5. Preserve current validation behavior while creating a cleaner seam for future grouped tool-exchange work.

## Near-Term Follow-Up

1. Add a first-class authoring/history helper that returns structured Python objects directly.
2. Make grouped tool-call/tool-return exchanges the default LLM-facing abstraction.
3. Keep raw provider-native message access as an internal/runtime-only interface.

## Constraints

- One broker should own conversation-history fidelity policy.
- Serialization should be an adapter concern, not where history logic lives.
- `core/memory` should remain extensible for future memory primitives such as vector retrieval.
