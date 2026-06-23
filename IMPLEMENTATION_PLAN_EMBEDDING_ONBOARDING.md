# Embedding Onboarding Hardening Plan

## Goal

Make the embedding provider contract visible in the model configuration UI and
fail session summarization before extraction when embeddings are unavailable.

## Current Contract

- `core/vector/service.py` builds `OpenAIEmbeddingModel` for every non-test
  embedding provider.
- Non-OpenAI providers only work when they expose an OpenAI-compatible
  embeddings endpoint through `base_url`.
- The UI lets users edit any provider on an embedding-capable model, which
  makes provider-native embedding support look broader than it is.
- `session_ops(operation="summarize_session")` requires embeddings to refresh
  session-summary vectors after extracting fields.
- If embedding generation fails during indexing, the summary write is rolled
  back, but the summarization model work has already been spent.
## Changes

- Update the model configuration UI so embedding-capable model aliases plainly
  state that only OpenAI embeddings are supported.
- Reject saving an embedding-capable model with any provider other than
  `openai`.
- Add a minimal embedding preflight before `summarize_session` extracts summary
  fields, so missing or unusable embedding setup fails before LLM extraction.
- Update the nightly session summarization workflow description to state the
  `embeddings` requirement and point to the session-summary docs.
- Document the current session-summary embedding requirement.
- Add installation guidance that the built-in nightly session summarization
  workflow requires `OPENAI_API_KEY` for the default `embeddings` model alias.

## Affected Areas

- `static/js/configuration.js`
- `core/tools/session_ops.py`
- `core/authoring/seed_templates/workflows/nightly-session-summarization.md`
- `docs/setup/installation.md`
- `docs/use/build-guide.md`

## Validation Target

- JavaScript syntax checks for changed frontend files.
- Python compile checks for changed backend files.
- Focused validation scenario covering `session_ops`.
- Manual diff review for the model configuration UI and workflow contract.
