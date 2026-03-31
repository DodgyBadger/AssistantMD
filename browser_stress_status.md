# Browser Stress Testing Status

## Current Status

The local environment parity blocker has been cleared and browser probes now run successfully in the rebuilt devcontainer.

This branch is no longer blocked on missing Playwright runtime setup. The original browser crash has not yet been reproduced in this environment.

### What we confirmed

- The running dev container did not match the production-style container setup.
- The live environment was running Python `3.13.12`.
- Before manual intervention, the browser tool failed locally because the Playwright Chromium runtime was missing.
- The repository does contain a real devcontainer setup under [`.devcontainer/`](/app/.devcontainer).
- After rebuild, the devcontainer now reports:
  - `python --version` -> `Python 3.13.12`
  - `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`
  - Chromium present at `/ms-playwright/chromium-1208/chrome-linux/chrome`
- A deterministic `data:` probe through [core/tools/browser.py](/app/core/tools/browser.py) `BrowserTool._browse` succeeded.
- Three repeated external probe rounds succeeded for:
  - `https://example.com`
  - `https://docs.python.org/3/`
  - `https://developer.mozilla.org/en-US/docs/Web/HTML`
- The repeated probe run emitted `browser_request_blocked` events while visiting MDN, which appears consistent with the tool's normal resource blocking policy, not a navigation failure.

### Why this mattered

The original browser crash report may still be real, but the dev environment was not trustworthy enough for browser stress testing because the browser runtime was not consistently provisioned.

## Changes Already Made

### Version consistency

- Updated [AGENTS.md](/app/AGENTS.md) to say Python `3.13`.
- Updated [docker/pyproject.toml](/app/docker/pyproject.toml) to align metadata/tooling with Python `3.13`:
  - `requires-python = ">=3.13"`
  - Ruff target `py313`
  - Black target `py313`
  - Mypy `python_version = "3.13"`

### Devcontainer browser parity

- Updated [`.devcontainer/devcontainer.json`](/app/.devcontainer/devcontainer.json) to set:
  - `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`
- Updated [`.devcontainer/Dockerfile`](/app/.devcontainer/Dockerfile) to export:
  - `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`
- Updated [`.devcontainer/setup.sh`](/app/.devcontainer/setup.sh) to install Playwright Chromium with deps:
  - `python3 -m playwright install --with-deps chromium`

## Remaining Known Difference vs Prod

- Devcontainer still runs as `root`.
- Production image in [docker/Dockerfile](/app/docker/Dockerfile) runs as `appuser`.

This was left unchanged for now because it is not the main blocker for browser-tool stress testing.

## Validation/Probe Notes

### Existing browser validation already in repo

- [validation/scenarios/integration/live/browser_policy_live.py](/app/validation/scenarios/integration/live/browser_policy_live.py)
  covers:
  - blocked local targets
  - selector-not-found guidance
  - large-output routing

### Existing stress-style experiment pattern

- [validation/scenarios/experiments/tavily_crawl_stress_assistant.py](/app/validation/scenarios/experiments/tavily_crawl_stress_assistant.py)
  is a good template for an experiment-style stress scenario.

### Browser tool implementation reviewed

- [core/tools/browser.py](/app/core/tools/browser.py)
  likely stress surfaces:
  - repeated Playwright launch/close behavior
  - navigation timeouts
  - real-site extraction heuristics on large or JS-heavy pages
  - browser output routing under large extracted content

## Probe Result Summary

### Deterministic probe

- `BrowserTool._browse` succeeded against a `data:` URL.
- Extracted selector was `main`.
- No launch failure, timeout, or extraction failure occurred.

### Repeated external probes

- Ran 3 rounds across 3 URLs for 9 total browser sessions.
- All 9 sessions completed successfully.
- Approximate timings:
  - `https://example.com`: first run about `6.0s`, later runs about `1.5s` to `1.8s`
  - `https://docs.python.org/3/`: about `1.3s` to `1.6s`
  - `https://developer.mozilla.org/en-US/docs/Web/HTML`: about `1.6s` to `1.7s`
- Observed extracted roots:
  - `example.com` -> `body`
  - Python docs -> `[role='main']`
  - MDN HTML page -> `main`

### Auto-buffer routing probe

- Ran a targeted in-process reproduction of the suspected path:
  1. fetch large content via [core/tools/browser.py](/app/core/tools/browser.py) `BrowserTool._browse`
  2. force low auto-buffer threshold
  3. route the result through [core/directives/tools.py](/app/core/directives/tools.py) `ToolsDirective._route_tool_output`
- Used a large `data:` page so the browser output reliably exceeded the threshold.
- Repeated 7 rounds.
- All 7 rounds succeeded.
- Each round produced a routed manifest and a numbered buffer:
  - `browser_output_000`
  - `browser_output_001`
  - `browser_output_002`
  - `browser_output_003`
  - `browser_output_004`
  - `browser_output_005`
  - `browser_output_006`
- Representative buffer metadata from the probe:
  - content size about `83,221` chars
  - estimated token count about `21,850`
  - `auto_buffered=True`

This means the direct browser -> auto-buffer routing branch is currently not reproducing the reported crash in local repro.

## Current Recommendation

Do not add a formal browser stress experiment yet.

The quick probe goal was to determine whether the previously reported browser instability was reproducible after fixing local environment parity. In this rebuilt environment, it was not reproducible.

The remaining gap is specificity: if there is still a browser crash report, the next useful step is to probe the exact failing URL/workflow pattern rather than adding a generic stress scenario that currently has no failing contract to capture.

The likely remaining unknown is not generic browser extraction or generic auto-buffer routing in isolation, but some higher-level interaction that was present in the original failing workflow:
- specific page structure
- tool-calling model behavior
- repeated workflow execution state
- prompt/context size interaction after routing

## Next If Needed

1. If the original failure involved a specific site or workflow step, reproduce against that exact target.
2. If a failure reappears, capture:
   - URL
   - wait mode
   - selector usage
   - whether failure happens on launch, navigation, or extraction
3. Only then add an experiment under [validation/scenarios/experiments/](/app/validation/scenarios/experiments/) if there is a concrete intermittent pattern worth preserving.

## Recommended Next Path

Use target-specific reproduction before adding new validation coverage.

1. Re-run probes only against the exact page or workflow that originally failed.
2. Add an experiment scenario only if that reproduces:
   - intermittent failures
   - timeout patterns
   - extraction instability
   - output-routing issues under larger content

## Notes

- Do not run the full validation suite directly; maintainers own that.
- If a scenario is added, prefer deterministic assertions on events/artifacts, not free-form assistant wording.
