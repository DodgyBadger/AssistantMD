# Configurable Validation Roots Plan

## Status

Implemented and verified from a checkout-local Python 3.13 UV environment. The
principal execution-authority scenario passes without an `/app` mount, explicit
root overrides pass a focused smoke check, and the production Python quality
gate is clean.

## Objective

Allow the scenario-validation harness to run from a UV virtual environment in
an arbitrary checkout path while preserving `/app` compatibility in the
devcontainer.

## Contract

- Discover the application root from the checkout by default.
- Allow `VALIDATION_APP_ROOT` to override fixture and default runtime roots.
- Allow `VALIDATION_ROOT` to override scenario discovery and evidence storage.
- Keep `CONTAINER_DATA_ROOT`, `CONTAINER_SYSTEM_ROOT`, and `SECRETS_PATH`
  authoritative when explicitly configured.
- Continue storing each scenario's mutable data under its isolated run folder.

## Affected Areas

- Validation CLI bootstrap paths
- Scenario discovery and evidence paths
- Shared fixture-source resolution
- Default validation secrets lookup
- Validation architecture documentation

## Validation Target

Run `integration/core/principal_execution_authority` from the checkout's Python
3.13 UV environment without an `/app` mount, then run focused Ruff and Black
checks for the modified harness files.

## Implementation Steps

1. Add one shared validation-path resolver.
2. Route the CLI, runner, base scenario, vault manager, and system controller
   through it.
3. Document defaults and environment overrides.
4. Run the targeted scenario and static checks.

## Next Phase

Maintainers can now run broader scenario groups from either the devcontainer or
a checkout-local UV environment. No further implementation is required for this
slice.
