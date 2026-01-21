# Validation Logger Artifacts Plan

## Goal
Enable validation scenarios to assert on in-flow artifacts emitted by the runtime (e.g., context manager step outputs) by introducing a validation-only logging sink in `UnifiedLogger`. These artifacts become first-class validation outputs and should be accessible using existing assertion helpers (with minor refactor to support non-vault roots).

## Design
- **Validation-only artifacts**: Add APIs in `UnifiedLogger` to emit structured YAML records when `RuntimeConfig.features["validation"] == True`.
- **Explicit instrumentation**: New helper methods make it obvious in code that these logs are validation artifacts (not general logs).
- **Artifact storage**: Write one YAML file per event under the validation run (`/app/validation/runs/<ts>_<scenario>/artifacts/validation_events/`).
- **Structured records**: YAML keeps machine-parsable key/values while staying readable.

### Proposed Logger API
```python
logger = UnifiedLogger(tag="context-manager")

logger.validation_event(
    "context_step_output",
    step_name="Summary",
    output=summary_text,
    model=model_name,
    ttl="weekly",
    cache_hit=False,
)

logger.validation_event(
    "context_step",
    step_name="Summary",
    model=model_name,
    ttl="weekly",
    output=summary_text,
)
```

### YAML Record Shape
```yaml
name: context_step
tag: context-manager
type: validation_event
timestamp: 2025-01-15T10:02:03.123Z
data:
  step_name: Summary
  model: gpt-mini
  ttl: weekly
  output: |
    <summary text>
```

## Plan of Attack
1. **Runtime config flag**
   - Extend `RuntimeConfig.for_validation(...)` to include an artifact directory:
     - `features={"validation": True, "validation_artifacts_dir": run_path / "artifacts"}`.

2. **UnifiedLogger validation sink**
   - Add helper functions:
     - `_validation_enabled()` checks runtime config `features["validation"]`.
    - `_validation_artifact_path()` resolves the validation events directory (use `features["validation_artifacts_dir"]` or fallback to `get_system_root().parent / "artifacts"`).
   - Add methods:
     - `validation_event(name: str, **data)`
   - Use a file lock to write per-event YAML safely.
   - No-ops outside validation.

3. **Assertion helpers refactor**
   - Generalize file-based assertions to support arbitrary roots:
     - `expect_file_created(vault, file_path, root=None)`
     - `expect_file_contains(vault, file_path, keywords, root=None)`
     - `expect_file_not_created(vault, file_path, root=None)`
   - Default `root` to the vault path for backward compatibility.
   - This lets scenarios assert on `self.run_path / "artifacts"` using the same helpers.

4. **First instrumentation hook**
   - Add a validation event to a high-value internal path (e.g., context manager step processing):
     - Emit per-step outputs and metadata (TTL, cache hit/miss, model, step name).
   - This creates immediately testable in-flow artifacts.

## Validation Scenario Example
```python
class ContextManagerArtifacts(BaseScenario):
    async def test_scenario(self):
        vault = self.create_vault("ContextVault")
        self.copy_files("validation/templates/...", vault)
        await self.start_system()

        await self.run_chat_prompt(
            vault=vault,
            prompt="Summarize the recent discussion.",
            session_id="ctx-001",
            tools=[],
            model="test",
        )

        events = self._load_validation_events(self.run_path / "artifacts" / "validation_events")
        # Assert against the event with name/context you care about.
```

## Notes
- The artifacts are explicit and controlled: only data intentionally emitted via `validation_event` is captured.
- YAML keeps auditability high while remaining simple to parse.
- This approach avoids relying on stdout or external Logfire backends.
