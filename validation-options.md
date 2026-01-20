# Validation Expansion Options

## Current Baseline
- Scenario-based validation focuses on user journeys and LLM outputs.
- Limited visibility into internal agent behavior.

## Options Discussed

### 1) Instrumented Validation Artifacts
- Add validation-only hooks to capture curated history delivered to chat agent.
- Store artifacts in run directory (deterministic, easy to assert).
- Pros: deterministic assertions, no external deps.
- Cons: requires code changes to emit artifacts.

### 2) Logfire Span-Based Evals (Pydantic Evals)
- Use Pydantic Evals with span-based evaluators to assert behavior via OpenTelemetry spans.
- Validate ordering and presence of context manager/chat spans.
- Pros: checks internal behavior; aligns with production telemetry.
- Cons: depends on span names/attributes being rich enough; setup cost.

### 3) Direct DB Assertions
- Assert `context_summaries` and `context_step_cache` in the run-local DB.
- Pros: low effort, deterministic.
- Cons: verifies persistence but not the full handoff to chat agent.

### 4) Deterministic Echo Model
- Add a deterministic validation model to reflect prompt inputs.
- Pros: full-path check including LLM output.
- Cons: model plumbing work; still not internal behavior.

### 5) Approval Testing on Artifacts
- Snapshot curated history / manager prompts / span traces (sanitized).
- Pros: good for structured outputs and regressions.
- Cons: needs normalization to avoid churn; LLM outputs not ideal.

## Recommended Near-Term Path
- Add instrumented artifacts for curated history + optional manager prompt.
- Add a small scenario to assert artifact content.
- Consider Pydantic Evals span-based checks as a second phase.
