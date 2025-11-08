# Validation Framework (Quick Guide)

End-to-end scenarios prove the AssistantMD works the way a real user
expects. Each scenario orchestrates the full system—vault setup, scheduler,
LLM execution, and artifact capture—using the high-level API in
`validation/core/base_scenario.py`.

## Philosophy

- Validate complete user journeys, not isolated functions.
- Operate on real vault layouts and assistant markdown.
- Keep scenario code readable so product stakeholders can follow the story.
- Collect evidence automatically so failures are easy to diagnose.

## How a Run Works

```
python validation/run_validation.py run
        ↓
ValidationRunner (validation/core/runner.py)
        ↓ discovers BaseScenario subclasses in validation/scenarios/
Scenario instance
        ↓ async test_scenario()
BaseScenario helpers manage vaults, time, API calls, LLM runs, evidence
        ↓
Artifacts saved under validation/runs/<timestamp>_<scenario>
```

## Scenario Anatomy

1. Create a Python file in `validation/scenarios/` (e.g. `weekly_planning.py`).
2. Place any supporting markdown templates in `validation/templates/`.
3. Import `BaseScenario` from `validation.core.base_scenario`.
4. Implement `async def test_scenario(self)` using high-level helpers.

Minimal example:

```python
from validation.core.base_scenario import BaseScenario

class TestWeeklyPlanning(BaseScenario):
    async def test_scenario(self):
        vault = self.create_vault("Planning")
        self.copy_files("validation/templates/assistants/daily_planner.md", vault, "assistants")

        await self.start_system()
        self.expect_vault_discovered("Planning")

        self.set_date("2025-01-06")
        await self.trigger_job(vault, "daily_planner")

        self.expect_file_created(vault, "2025-01-06.md")
        await self.stop_system()
        self.teardown_scenario()
```

Scenarios can call `await self.start_system()` multiple times, interact with the
chat UI (`start_chat_session`, `send_chat_message`), or exercise REST/CLI
surfaces via `call_api` and `launcher_command`.

## BaseScenario Surface

| Capability | Key helpers |
| --- | --- |
| Vault setup | `create_vault`, `copy_files`, `create_file` |
| Time & pattern control | `set_date`, `advance_time`, `trigger_job`, `wait_for_real_execution` |
| System lifecycle | `start_system`, `stop_system`, `restart_system`, `trigger_vault_rescan` |
| Workflow execution | `run_assistant`, `expect_scheduled_execution_success`, `get_job_executions` |
| Assertions | `expect_file_created`, `expect_file_contains`, `expect_vault_discovered`, `expect_assistant_loaded`, `expect_scheduler_job_created`, etc. |
| Chat and API | `run_chat_prompt`, `clear_chat_session`, `call_api`, `launcher_command` |
| Evidence & teardown | `timeline_file`, `system_interactions_file`, `critical_errors_file`, `teardown_scenario()` |

## Working With Secrets During Validation

- Place developer API keys in `validation/secrets_override/secrets.yaml`. The validation harness points
  `SECRETS_BASE_PATH` at that file so scenarios can read real credentials without modifying your
  production `system/secrets.yaml`.
- Each scenario run creates a temporary overlay secrets file under
  `validation/runs/<timestamp>_<scenario>/system/secrets.yaml`. Endpoint calls that update secrets
  write to this overlay and the file is removed when the run completes.
- To override or add secrets for a specific scenario, call the `/api/system/secrets` endpoint within
  the scenario. Changes affect only the run-local overlay and won’t leak into the shared base file.

Each helper logs to the scenario timeline while delegating to services in
`validation/core/` (vault manager, system controller, time controller, workflow
execution, chat execution).

Directive and workflow semantics remain untouched: scenarios observe outcomes;
control flow decisions stay inside production code.

## Evidence & Issues

- Every scenario run writes to `validation/runs/<timestamp>_<scenario>/`.
  - `artifacts/timeline.md` – chronological log of everything the scenario did.
  - `artifacts/system_interactions.log` – API/chat payloads and responses.
  - `artifacts/critical_errors.md` – high-priority failures for follow-up.
  - `test_vaults/` – the actual vault contents after the run.
- `validation/issues_log.md` automatically tracks failing scenarios and system
  errors so the team has a single backlog of problems to investigate.

## Tips for Fast Iteration

- Use the `@model test` directive to avoid external LLM calls when you only need
  to confirm workflow wiring.
- `set_date()` (and `advance_time()`) only change how patterns such as `{today}`
  resolve; they do **not** advance APScheduler’s clock. To execute a scheduled
  run immediately, call `trigger_job` or `wait_for_real_execution`.
- `validation/templates/assistants/` and `validation/templates/files/` provide
  reusable fixtures so scenarios stay concise.
- `call_api("/api/...")` uses FastAPI's `TestClient` under the hood, letting you
  exercise REST endpoints without running uvicorn; requests reuse the same
  validation vault paths configured for the scenario.

## Running Scenarios

```bash
# Run specific scenarios
python validation/run_validation.py run weekly_planning,basic_haiku

# Filter by name pattern
python validation/run_validation.py run --pattern planner

# List available scenarios with descriptions
python validation/run_validation.py list
```

The CLI prints pass/fail summaries, points you to the evidence directory, and
reminds you to review `validation/issues_log.md` when something breaks.
