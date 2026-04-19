## Unified Thinking Plan

### Goal
- Replace the current provider-specific / string-encoded thinking behavior with one internal thinking contract based on Pydantic AI's unified `ModelSettings.thinking`.
- Make thinking controllable in one consistent way from:
  - chat / default model execution
  - workflow/context model alias usage
  - authoring `generate(...)`
  - configuration UI / persisted general settings

### Current State
- `core/llm/model_factory.py`
  - Parses `model_alias (thinking=true|false)` via `DirectiveValueParser`.
  - Applies thinking only for Anthropic today by setting `anthropic_thinking={"type": "enabled", "budget_tokens": 2000}`.
  - Does not apply unified `ModelSettings.thinking` for OpenAI, Google, Grok, Mistral, or OpenAI-compatible providers.
- `core/utils/value_parser.py`
  - Supports parenthesized per-model parameters and currently documents `thinking`.
- `core/llm/agents.py`
  - Uses `settings.default_model` verbatim and passes it into `build_model_instance(...)`.
  - There is no first-class persisted default thinking policy yet.
- `core/chat/executor.py`
  - Chat model selection converges on `build_model_instance(...)`.
- `core/authoring/helpers/generate.py`
  - `options={"thinking": bool}` is translated into a model-string suffix: `model="x (thinking=true|false)"`.
  - This is an authoring-only path and currently requires an explicit `model=...`.
- `core/settings/settings.template.yaml`
  - Has `default_model` but no separate thinking policy setting.
- `static/js/configuration.js`
  - General settings are already editable through the configuration UI, so a first-class persisted thinking setting can ride the existing settings surface.

### Problems To Fix
- Thinking is configured through ad hoc string decoration rather than a typed runtime contract.
- Provider handling is inconsistent; Anthropic has bespoke logic while other providers mostly ignore the toggle.
- The UI cannot expose one universal thinking preference cleanly because the current state is buried inside model strings.
- `generate(...)` treats thinking as an authoring helper quirk instead of part of normal model execution configuration.
- The current contract only supports boolean on the authoring side, while Pydantic AI now supports `True` / `False` plus effort levels such as `minimal|low|medium|high|xhigh`.
- Model-string encoded thinking should be removed, not preserved.

### Target Contract
- Canonical internal representation:
  - `thinking: None | bool | str`
  - `None` means "use provider/model default"
  - `False` means "disable when supported"
  - `True` means "enable with provider default effort"
  - string values mean explicit effort level
- Canonical model-construction path:
  - `build_model_instance(...)` computes base provider settings, then injects unified `thinking` into the model's `settings` object instead of writing provider-specific thinking fields directly.
- Canonical persisted configuration:
  - add a general setting for default thinking policy, separate from `default_model`
  - likely shape: `default_model_thinking`
  - recommended stored values: `default`, `off`, `on`, `minimal`, `low`, `medium`, `high`, `xhigh`
  - map `default -> None`, `off -> False`, `on -> True`

### Scope
- In scope:
  - internal thinking parsing and normalization
  - model factory wiring
  - default model / chat behavior
  - authoring `generate(...)` options
  - configuration setting and UI exposure
  - docs and validation scenarios affected by the new contract
- Out of scope for the first pass:
  - provider-specific reasoning summaries or encrypted reasoning content
  - custom UI widgets beyond the existing general-settings editor unless the current plain-text editor proves too confusing
  - broad cleanup of unrelated stale DSL references outside the directly affected path

### Implementation Steps
1. Introduce a normalized thinking parser in `core/llm`.
   - Add a helper that accepts raw user/config values and returns `None | bool | ThinkingLevel`.
   - Support:
     - future explicit effort values like `thinking=high`
     - persisted setting values like `default|off|on|high`
   - Centralize validation here so chat, config, workflow/context execution, and authoring share one interpretation.

2. Refactor `build_model_instance(...)` to accept normalized thinking input.
   - Stop parsing thinking from model-string parameters.
   - Resolve thinking once from explicit inputs and persisted settings, then pass `thinking=...` through the provider settings object:
     - `AnthropicModelSettings`
     - `GoogleModelSettings`
     - `OpenAIResponsesModelSettings`
     - shared `ModelSettings` for providers using the common path
   - Remove the hard-coded Anthropic `anthropic_thinking` budget behavior unless a temporary compatibility branch is required for specific model aliases.

3. Add a first-class default thinking general setting.
   - Update `core/settings/settings.template.yaml` with a new root setting.
   - Reuse existing general-settings persistence in `core/settings/store.py` and `core/settings/config_editor.py`.
   - In `core/llm/agents.py`, apply the default thinking setting when no explicit per-call/per-model override is present.
   - Do not encode this into `default_model`; keep model identity and thinking policy separate.

4. Update precedence rules.
   - Recommended precedence:
     1. explicit per-call override (`generate(..., options=...)`, explicit workflow/context/chat thinking input if present)
     2. global default thinking setting
     3. provider/model default
   - Document this in code and user-facing docs.

5. Upgrade authoring `generate(...)`.
   - Replace `_apply_options_to_model(...)` string concatenation with a typed resolution path.
   - Allow `options["thinking"]` to accept:
     - `true` / `false`
     - effort strings
     - optionally `null` / omitted for default behavior
   - Remove the current restriction that thinking requires an explicit model if the global/default path can supply it safely.
   - Update `core/authoring/stubs.pyi`, helper contract docs, and examples.

6. Remove model-string encoded thinking from the active path.
   - Delete the `thinking` model-string parsing path from `build_model_instance(...)`.
   - Delete the authoring helper logic that appends ` (thinking=...)` to model aliases.
   - If any active runtime entry point still attempts to supply thinking via encoded model strings, fail clearly instead of adding compatibility shims.

7. Update configuration/UI copy.
   - Add the new setting description to `core/settings/settings.template.yaml`.
   - Confirm the existing general settings editor in `static/js/configuration.js` presents it clearly.
   - If plain-text editing is too ambiguous, add lightweight guidance text for accepted values rather than building a custom control in the first pass.

8. Audit docs and examples.
   - Update any docs/examples that currently describe thinking as Anthropic-only or model-string-only behavior.
   - Update `generate(...)` contract text to describe the new accepted values and default-setting interaction.

### Affected Areas
- [core/llm/model_factory.py](/app/core/llm/model_factory.py)
- [core/utils/value_parser.py](/app/core/utils/value_parser.py)
- [core/llm/agents.py](/app/core/llm/agents.py)
- [core/chat/executor.py](/app/core/chat/executor.py)
- [core/authoring/helpers/generate.py](/app/core/authoring/helpers/generate.py)
- [core/authoring/stubs.pyi](/app/core/authoring/stubs.pyi)
- [core/settings/settings.template.yaml](/app/core/settings/settings.template.yaml)
- [core/settings/store.py](/app/core/settings/store.py)
- [core/settings/config_editor.py](/app/core/settings/config_editor.py)
- [static/js/configuration.js](/app/static/js/configuration.js)

### Validation Targets
- Focused local checks:
  - thinking normalization:
    - `default -> None`
    - `off -> False`
    - `on -> True`
    - explicit effort values
    - invalid thinking values
  - model-factory construction for:
    - bare alias with no explicit thinking
    - explicit thinking input
    - default-setting fallback
    - precedence of call override over default setting
  - authoring helper behavior for:
    - boolean thinking
    - effort-level thinking
    - omitted thinking
    - default-model behavior without explicit `model=...`
- Minimal scenario-level validation to request from maintainers:
  - extend `validation/scenarios/integration/core/authoring_contract.py`
    - keep the existing workflow and add one `generate(...)` call that exercises explicit thinking input
    - assert deterministic validation events around thinking resolution rather than model output wording
  - avoid adding a brand-new scenario unless the existing authoring contract scenario cannot express the precedence case cleanly
- Recommended event contract:
  - add one minimal decision-boundary event such as `authoring_thinking_resolved`
  - minimum payload keys:
    - `workflow_id`
    - `model`
    - `requested_thinking`
    - `resolved_thinking`
    - `source`
  - fire once per generate/model-resolution path, only after the final effective thinking value is known
- Explicit non-goal:
  - do not try to validate that hidden reasoning actually occurred
  - do not assert on provider-returned thinking parts or free-form model wording

### Risks / Decisions
- Pydantic AI silently ignores unified thinking for unsupported models/providers. That is useful, but it can hide misconfiguration. We should decide whether to log when the app requests thinking for a provider/model profile that does not support it.
- Some providers/models may still need provider-specific settings for advanced reasoning features. The first pass should standardize the base toggle and effort levels, not every advanced provider feature.
- If any active caller still passes thinking encoded inside model strings, prefer explicit failure over compatibility shims.

### Persistence / Runtime State Notes
- This plan changes persisted configuration in `/app/system/settings.yaml` by adding a new general setting.
- No secrets changes are required.
- Runtime behavior should move to the clean typed path without preserving model-string encoded thinking.

### Next Phase
- Move to Feature Development after implementing the normalization helper, model-factory refactor, and the new general setting together as one vertical slice.
