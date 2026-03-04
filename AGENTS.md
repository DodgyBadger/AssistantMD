# Agent Operating Guide

AssistantMD is a single-user, markdown-first agent system with a Python backend, FastAPI API/UI surface, and scenario-based validation harness.

## Essentials (Always Check First)
- Python version: `3.12`.
- Non-standard build command: `npm run build:css` compiles `static/input.css` to `static/output.css`.
- Validation ownership: maintainers run full validation (`python validation/run_validation.py ...`); agents should request results instead of running the suite.
- Validation-first delivery: follow [Testing and Validation](/app/docs/agent-guides/testing-and-validation.md#validation-first-workflow).

## Detailed Guides
- [Project Structure](/app/docs/agent-guides/project-structure.md)
- [Coding Standards](/app/docs/agent-guides/coding-standards.md)
- [Testing and Validation](/app/docs/agent-guides/testing-and-validation.md)
- [Git and Review Workflow](/app/docs/agent-guides/git-and-review.md)
- [Security and Runtime State](/app/docs/agent-guides/security-and-state.md)

## Durability Principle
This codebase will outlive any single contributor.  
Every shortcut becomes future maintenance cost.  
Fight entropy and leave the codebase better than you found it.
