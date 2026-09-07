# Default Model Seed Currentness Plan

Status: implemented
Audit date: 2026-09-07

## Goal

Refresh the curated model aliases in `core/settings/settings.template.yaml` so a
new AssistantMD installation starts with model IDs that represent each built-in
hosted provider's current general-purpose lineup, while preserving stable
AssistantMD aliases and accurate capability gates.

This effort covers providers that have at least one model in the packaged seed:
Google, Anthropic, OpenAI, xAI (`grok`), and Mistral. OpenRouter, LM Studio, and
Ollama remain provider entries without packaged model aliases because their
available models depend on routing or the user's local installation.

## Current Contract and Constraints

- The settings template is the seed for a missing `system/settings.yaml` and the
  source used by the explicit settings-repair flow.
- `system/settings.yaml` is persistent runtime state and must not be edited as
  part of this change.
- Model entries are user-editable. Settings repair preserves existing entries,
  so changing a seeded `model_string` affects fresh installations but does not
  silently migrate an existing user's model selection.
- The default model remains the stable AssistantMD alias `sonnet`; updating that
  alias's target refreshes fresh installations without changing the default
  setting or authored content.
- Capability metadata is a runtime gate, not descriptive decoration. Every
  retained chat model must continue to declare `text`, and declare `vision`
  only when the provider documents image input support.
- OpenAI's `embeddings` alias is a separate vector-space contract. Changing it
  would require an index migration/rebuild design and is outside this refresh.
- The installed Pydantic AI 2.19.0 model types accept arbitrary provider model
  strings, and its bundled known-name lists already include the recommended
  Anthropic, OpenAI, Google, and xAI generations. Model-name acceptance does not
  replace a live provider smoke test.

## Audit Findings and Proposed Seed

| AssistantMD alias | Seeded model | Proposed model | Decision |
| --- | --- | --- | --- |
| `gemini` | `gemini-2.5-pro` | `gemini-3.1-pro-preview` | Update, but mark/release-note that Google's current Pro model is preview-only. If preview models are not acceptable seed policy, retain 2.5 Pro until a Gemini 3 Pro GA model exists. |
| `gemini-flash` | `gemini-2.5-flash` | `gemini-flash-latest` | Use Google's rolling alias for the current general-purpose Flash model. |
| `gemini-flash-lite` | `gemini-2.5-flash-lite` | `gemini-flash-lite-latest` | Use Google's rolling alias for the current cost/throughput tier. |
| `sonnet` | `claude-sonnet-4-5` | `claude-sonnet-5` | Update to the current Sonnet tier. |
| `opus` | `claude-opus-4-1` | `claude-opus-5` | Urgent update: the seeded Opus 4.1 model retired on 2026-08-05. |
| `haiku` | `claude-haiku-4-5` | `claude-haiku-4-5` | Keep. Haiku 4.5 remains Anthropic's current fast tier and the accepted convenience alias avoids an unnecessary identifier-only change. |
| `astra` | absent | `gpt-6-astra` | Add OpenAI's most capable model as an explicit opt-in alias for API and eligible OAuth users. Its higher cost and narrower availability are why it does not replace `gpt`. |
| `gpt` | `gpt-5` | `gpt-5.6-sol` | Update the existing general-purpose alias to the current, less expensive flagship family. |
| `gpt-mini` | `gpt-5-mini` | `gpt-5.6-terra` | Keep the application alias because authored workflows use it; target the current balanced intelligence/cost tier. |
| `gpt-nano` | `gpt-5-nano` | `gpt-5.6-luna` | Keep the application alias and target the current high-volume, cost-sensitive tier. |
| `embeddings` | `text-embedding-3-small` | `text-embedding-3-small` | Keep. It remains offered, and changing embedding space is not a routine model-list refresh. |
| `grok` | `grok-4` | `grok-4.6-latest` | Update to xAI's current frontier general-purpose model using its rolling family alias. |
| `grok-mini` | `grok-3-mini` | remove | Remove from the fresh-install seed. It is absent from xAI's current recommended lineup and there is no current “mini” successor with the same semantics. |
| `grok-fast` | absent | `grok-4.3-latest` | Add the lower-cost, high-throughput general-purpose choice using xAI's rolling family alias. This is clearer than silently repointing `grok-mini`. |
| `mistral-large` | `mistral-large-latest` | unchanged | Keep. Mistral documents `-latest` as the moving alias for the newest GA family member; it currently represents Mistral Large 3. |
| `mistral-medium` | `mistral-medium-latest` | unchanged | Keep. The alias tracks the current GA Mistral Medium line, currently Medium 3.5. |
| `mistral-small` | `mistral-small-latest` | unchanged | Keep. The alias tracks the current GA Mistral Small line, currently Small 4. |
| `magistral-medium` | `magistral-medium-latest` | remove | Remove from the fresh-install seed. Native Magistral reasoning is deprecated; Mistral directs new integrations to Medium 3.5 with `reasoning_effort`. |
| `magistral-small` | `magistral-small-latest` | remove | Remove from the fresh-install seed. Native Magistral reasoning is deprecated; Mistral directs new integrations to Small 4 with `reasoning_effort`. |

All proposed Google, Anthropic, OpenAI, xAI, and retained Mistral chat models
support text and image input according to their current provider documentation,
so their seeded `capabilities: ["text", "vision"]` values remain appropriate.

Anthropic also offers Claude Fable 5.1 above its Opus tier. Do not add it in this
narrow seed refresh: Anthropic documents provider-specific refusal, fallback,
and billing behavior for Fable, which deserves an integration/evaluation slice
rather than an unvalidated picker entry.

## Authoritative Sources

- [Google Gemini model catalog](https://ai.google.dev/gemini-api/docs/models)
  and [deprecation schedule](https://ai.google.dev/gemini-api/docs/deprecations)
- [Anthropic model overview](https://platform.claude.com/docs/en/models/overview)
  and [model deprecations](https://docs.anthropic.com/en/docs/about-claude/model-deprecations)
- [OpenAI model catalog](https://developers.openai.com/api/docs/models)
- [xAI Grok 4.6](https://docs.x.ai/developers/grok-4-6),
  [current pricing/model lineup](https://docs.x.ai/developers/pricing), and
  [model retirement guidance](https://docs.x.ai/developers/migration/may-15-retirement)
- [Mistral model catalog](https://docs.mistral.ai/models),
  [model lifecycle and aliases](https://docs.mistral.ai/inference/model-lifecycle),
  and [deprecated native reasoning guidance](https://docs.mistral.ai/resources/deprecated/native-reasoning)

## Implementation Scope

1. Update only the `models` mapping in
   `core/settings/settings.template.yaml` according to the table above.
2. Preserve the existing AssistantMD aliases used by product defaults and seeded
   workflows (`sonnet`, `gpt-mini`, and the other retained names).
3. Add `astra`, replace `grok-mini` with `grok-fast`, and remove the two
   `magistral-*` entries.
4. Keep provider records, secret pointers, embedding dimensions, default model,
   and persistent runtime settings unchanged.
5. Do not add an automatic settings upgrade for old model IDs. Rewriting a
   user-editable model mapping would violate the current non-destructive repair
   contract. A future migration would need to update only exact, known packaged
   defaults and be separately approved and validated.

## Validation Target

This is a static seed-data refresh and does not change the existing copy or
repair behavior, so a focused smoke check is proportionate to the change. The
implemented check verifies that:

- the packaged template parses through `SettingsFile`;
- each retained/new alias resolves to the expected provider, model string, and
  capability set;
- `embeddings` remains OpenAI `text-embedding-3-small` at 1536 dimensions; and
- removed aliases are absent from the fresh-install seed.

The smoke check passed with 16 models and 8 providers. `git diff --check` also
passed. No new validation event or integration scenario is needed because the
settings copy/repair decision path is unchanged.

Live calls are optional diagnostics, not deterministic merge gates. If API keys
are available, request a maintainer-run one-turn text/tool smoke test for each
new model ID and an image-input smoke test for one model per provider before
release.

## Next Phase

The seed update and targeted deterministic checks are complete. Before merge,
request the maintainer-owned `integration/core` validation result; agents should
not run that full suite.
