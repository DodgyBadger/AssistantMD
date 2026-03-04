# Project Structure

- `core/`: backend runtime, tools, workflow parsing, ingestion, scheduling, settings.
- `api/`: FastAPI API models, endpoints, and service wrappers.
- `validation/`: scenario framework, runners, templates, and run artifacts (`validation/runs/`).
- `static/`: frontend assets (`index.html`, `app.js`, Tailwind input/output CSS).
- `docs/`: setup, usage, and architecture references.
- `docker/`: container build context and Python project config (`pyproject.toml`, `uv.lock`).

## Module Placement Rules
- Keep side-effect-heavy logic in `core/` services.
- Keep API layer thin (`api/` should orchestrate, not own business logic).
- For new Python modules, place the primary class/function near the top; helpers follow below or live in utility modules.
