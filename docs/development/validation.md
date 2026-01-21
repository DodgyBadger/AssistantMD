# Validation Framework

Run scenarios that exercise features and use cases. Assert functionality by checking expected outputs (both intermediate and end-user). Each scenario spins up a complete sandboxed runtime.

Scenarios can be narrow (e.g. verifying a single prompt composition rule) or broad (snapshotting an entire workflow run).

**Core principles:**
- Validate use cases, features and internal decision points, not isolated functions.
- Reduce maintenance burden by loosely coupling scenarios to production code through system and end-user outputs.
- Scenarios should be readable and high-level. Avoid dense code.
- Use the helpers provided by BaseScenario and avoid mocking.
- Collect evidence automatically so failures are easy to diagnose and review.

## Framework anatomy

**Scenario**: A Python class that tests some aspect of the system. It sets up one or more sandbox vaults and the files needed for the test, launches the runtime, uses `BaseScenario` helpers to trigger code paths and then asserts on artifacts.  

**Run**: One execution of a scenario. Each run gets a dedicated folder under `validation/runs/` containing the scenario vault(s), system folder and artifacts.  

**Artifacts**: Evidence emitted during a run such as run and system logs, outputs of the feature being exercised (e.g. chat response, workflow output) and internal events emitted via `UnifiedLogger.validation_event`.  

**Assertions**: Checks against artifacts that validate expected functionality. The collection of assertions in a scenario is what passes or fails the run.


## Framework flow

**Define** a scenario class in `validation/scenarios/`
- use helpers provided by `BaseScenario` (inspect the class for the full interface)
- prefer bundling fixtures directly in the scenario; use `validation/templates/` only for shared assets
- related scenarios can be grouped into subfolders and run as a group

**Run** it via `validation/run_validation.py`
- the runner discovers the class, boots a sandboxed runtime, and executes `test_scenario`
- validation framework prunes to 10 most recent runs

**Review** artifacts under `validation/runs/`
- timeline, logs, validation events, vault outputs

See `validation/scenarios/integration/basic_haiku.py` for a minimal example.


## Working with secrets during validation

- By default, validation runs use the configured secrets file (`SECRETS_PATH` if set, otherwise
  `system/secrets.yaml`). API calls that update secrets write to that same file.
- To isolate secrets for a specific run, set `SECRETS_PATH` before starting the system and point it
  at a run-local file (for example, `validation/runs/<timestamp>_<scenario>/system/secrets.yaml`).
  This keeps scenario updates scoped to the run folder.
  You can set this inside the scenario file itself (before calling `start_system()`), for example
  by assigning `os.environ["SECRETS_PATH"]` at the top of `test_scenario`.

## Validation events

Use validation events when you need to assert on intermediate state that is not visible in final outputs (for example, prompt composition or step-level decisions). This is accomplished using `UnifiedLogger.validation_event` in the code where you want to emit the event. These only fire when the app is run through the validation framework - they will not fire when running in production. `validation_event` accepts any key/value pairs you want to capture; the example below is illustrative.

```python
logger = UnifiedLogger(tag="step-workflow")

logger.validation_event(
    "workflow_step_prompt",
    step_name=step_name,
    output_file=output_file_path,
    prompt=final_prompt,
)
```

Each call writes a single YAML file under:
`validation/runs/<timestamp>_<scenario>/artifacts/validation_events/`.

The YAML includes `name`, `tag`, `timestamp`, trace information and the `data` captured in the call.

### How to Assert in Scenarios

Load a YAML event file (via `BaseScenario.load_yaml`) and assert on structured fields.

```python
event_path = self.run_path / "artifacts" / "validation_events" / "0001_step-workflow_workflow_step_prompt.yaml"
event = self.load_yaml(event_path) or {}

self.expect_true(event.get("data", {}).get("step_name") == "PATHS_ONLY")
self.expect_true("INLINE_CONTENT" in event.get("data", {}).get("prompt", ""))
```

## Running Scenarios

```bash
# List available scenarios with descriptions
python validation/run_validation.py list

# Run specific scenario(s)
python validation/run_validation.py run integration/basic_haiku
python validation/run_validation.py run integration/basic_haiku, integration/tool_suite

# Run all scenarios in a folder
python validation/run_validation.py run integration

# Filter by name pattern
python validation/run_validation.py run --pattern planner
```

## Tips for fast iteration

- Use the `@model test` directive to avoid external LLM calls when you only need   to confirm workflow wiring.
- `set_date()` (and `advance_time()`) only change how patterns such as `{today}` resolve; they do **not** advance APScheduler’s clock. To execute a scheduled workflow immediately, call `trigger_job` or `wait_for_real_execution`.
- `call_api("/api/...")` uses FastAPI's `TestClient` under the hood, letting you exercise REST endpoints without running uvicorn; requests reuse the same validation vault paths configured for the scenario.

## Bootstrap note

- Path helpers require either bootstrap roots or a runtime context. The validation CLI seeds bootstrap roots before importing path-dependent modules so scenarios run in isolation without env hacks.
- If you write custom validation utilities or ad-hoc scripts, set bootstrap roots early (for example, `set_bootstrap_roots(test_data_root, run_path / "system")`) or start a runtime context before importing modules that resolve settings/paths.
