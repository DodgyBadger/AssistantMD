# Pattern Format Implementation Plan

## Goals
- Add explicit, optional date formatting to time-based patterns (e.g., `{today:YYYYMMDD}`) while preserving backward compatibility.
- Centralize default formats inside the formatting logic (not duplicated by callers), so future changes require a single edit.
- Update documentation and validation scenarios to reflect new formatting capabilities.
- Establish a reliable integration checkpoint by running validation scenarios *before* changes and then after implementation.
- Use ephemeral bash tests after key milestones to confirm interfaces and minimize regressions.

## Scope
- Update `core/utils/patterns.py` to parse optional format suffixes and to format dates via a centralized formatter.
- Update directive processors (`core/directives/input.py`, `core/directives/output.py`, `core/directives/header.py`) to pass full pattern strings into a shared resolver while keeping existing behavior.
- Update docs in `docs/use/patterns.md` and reference tables as needed.
- Add or update validation scenarios under `validation/scenarios/`.

## High-Level Design
### 1) Centralized formatting API
Introduce a new formatter in `PatternUtilities` that:
- Accepts a `datetime` and an optional format string.
- Applies default formats when the format string is absent, using centralized defaults:
  - Date default: `YYYY-MM-DD`
  - Month default: `YYYY-MM`
  - Day name default: existing (full day name)
  - Month name default: existing (full month name)
- Supports token replacement order (longest first): `YYYY`, `MMMM`, `MMM`, `YY`, `MM`, `M`, `DD`, `D`, `dddd`, `ddd`, optionally `HH`, `mm`, `ss` later.

### 2) Pattern parsing
Enhance parsing so `{today:YYYYMMDD}` is allowed without interfering with `{latest:3}` and `{pending:5}`.
- Add a new helper: `parse_pattern_with_optional_format(pattern: str) -> tuple[str, Optional[str]]`.
- Keep `parse_pattern_with_count()` for count-based patterns.
- Ensure logic differentiates:
  - Date patterns with `:format` (e.g., `today:YYYYMMDD`).
  - Count-based patterns (e.g., `latest:3`, `pending:5`).
  - Validation for invalid formats should be permissive (treat as literal string) or strict (raise) — choose and document.

### 3) Resolution
Modify `resolve_date_pattern()` to accept *the full pattern string*, parse optional format, and route to the centralized formatter:
- Input: `pattern` possibly containing `:<format>`.
- Output: formatted string.
- Keep all default behavior when `:<format>` is absent.

### 4) Caller updates
`@input`, `@output`, and `@header` should resolve by passing full pattern strings to `resolve_date_pattern()` (not their own format logic).
- For `@output` and `@header`, multi-file and `{pending}` checks should operate on the base pattern and count before formatting.
- For `@input` single-time patterns, keep current behavior but route through the updated resolver.

## Implementation Steps
### Step 0 — Close existing docs/code gap (pre-work) ✅
- `@output` docs already claim `{day-name}` and `{month-name}` are supported, but the output directive does not resolve them today.
- Update `core/directives/output.py` to route `{day-name}` and `{month-name}` through `resolve_date_pattern()` just like headers.
- Re-run the new `integration/pattern_substitution` scenario to confirm alignment before further changes.

### Milestone 0 — Baseline validation checkpoint (no code changes) ✅
- Run a focused validation suite to ensure stable baseline. Suggested commands:
  - `python validation/run_validation.py list`
  - `python validation/run_validation.py run integration` (or the subset currently used by CI/maintainers)
- Record pass/fail to ensure a clean checkpoint.

### Milestone 1 — Pattern utility refactor (core/utils/patterns.py) ✅
1. Add formatting logic:
   - `format_datetime(dt, fmt: Optional[str], default: str) -> str`
   - Token replacement order: longest to shortest to avoid partial collisions.
2. Add parser for optional format suffix:
   - `parse_pattern_with_optional_format(pattern: str) -> tuple[str, Optional[str]]`
3. Update `resolve_date_pattern()` to:
   - Parse optional format suffix.
   - Choose default format based on pattern type (date vs month vs name).
   - Format using centralized formatter.

Ephemeral tests (bash) after this milestone:
- `python - <<'PY'
from datetime import datetime
from core.utils.patterns import PatternUtilities

ref = datetime(2026, 2, 10)
print(PatternUtilities.resolve_date_pattern('today', ref))
print(PatternUtilities.resolve_date_pattern('today:YYYYMMDD', ref))
print(PatternUtilities.resolve_date_pattern('this-month:YYYYMM', ref))
print(PatternUtilities.resolve_date_pattern('day-name:ddd', ref))
PY`
Expected:
- `2026-02-10`
- `20260210`
- `202602`
- `Tue` (or equivalent for the date)

### Milestone 2 — Directive integration ✅
- Update `@output` and `@header` to pass the full pattern string into `resolve_date_pattern()` once base pattern validation succeeds.
- Ensure validation for `{pending}` and multi-file patterns still applies based on the base pattern/count (not format suffix).
- Update `@input` single-pattern logic to allow format suffix without conflicting with count-based patterns.

Ephemeral tests (bash) after this milestone:
- Create a short script to instantiate the directive processors and resolve values with known reference dates.

### Milestone 3 — Docs updates ✅
- Update `docs/use/reference.md` (Patterns table) to mention format suffix.
- Ensure doc examples reflect backward compatibility and defaults.

### Milestone 4 — Validation scenarios ✅
- Add/extend validation scenarios that exercise:
  - `{today:YYYYMMDD}` in `@output` and `@header`.
  - `{this-week:YYYYMMDD}` in `@output`.
  - `{this-month:YYYYMM}` in `@output` and `@header`.
  - Backward compatibility without format suffix.
- Prefer scenario tests that verify generated path/header contents rather than raw helper output.

### Milestone 5 — Integration validation ✅
- Re-run the same validation set as Milestone 0 to ensure stability and detect regressions.
- If failures, inspect artifacts under `validation/runs/` and adjust.

## Risks & Mitigations
- **Ambiguous colon usage**: `parse_pattern_with_count()` may incorrectly interpret format strings as counts. Mitigate by parsing optional format only for time-based patterns; keep count parsing for `{latest:3}` and `{pending:5}` only.
- **Token collisions**: Ensure replacement order is from longest to shortest (e.g., `YYYY` before `YY`, `MMMM` before `MMM`).
- **Unrecognized formats**: Decide whether to leave tokens intact or raise. For now, prefer permissive (leave unknown tokens as-is) to avoid breaking workflows.

## Files Touched (Expected)
- `core/utils/patterns.py`
- `core/directives/input.py`
- `core/directives/output.py`
- `core/directives/header.py`
- `docs/use/patterns.md`
- `docs/use/reference.md`
- `validation/scenarios/...` (new or updated)

## Notes
- Defaults must be centralized in the formatting logic in `PatternUtilities`. Callers should not embed any format defaults.
- Keep backward compatibility: if no explicit `:<format>` is provided, output should remain unchanged relative to current behavior.
