"""
Integration scenario that validates pattern substitutions for @output and @header.

Focuses on time-based and name-based patterns with deterministic reference dates.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class PatternSubstitutionScenario(BaseScenario):
    """Validate pattern substitutions resolve to expected file paths and headers."""

    async def test_scenario(self):
        vault = self.create_vault("PatternVault")
        self.create_file(
            vault,
            "AssistantMD/Workflows/pattern_substitution.md",
            PATTERN_SUBSTITUTION_WORKFLOW,
        )

        checkpoint = self.event_checkpoint()
        await self.start_system()

        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="workflow_loaded",
            expected={"workflow_id": "PatternVault/pattern_substitution"},
        )

        # Deterministic reference date for predictable substitutions
        reference_date = datetime(2026, 2, 12)  # Thursday
        self.set_date(reference_date.strftime("%Y-%m-%d"))

        result = await self.run_workflow(vault, "pattern_substitution")
        assert result.status == "completed", "Workflow should complete"

        expected = self._expected_outputs(reference_date)
        for relative_path, header_value in expected.items():
            output_path = vault / relative_path
            assert output_path.exists(), f"Expected {relative_path} to be created"
            content = output_path.read_text(encoding="utf-8")
            first_line = content.splitlines()[0] if content else ""
            assert first_line == f"# {header_value}", (
                f"Expected header '{header_value}' in {relative_path}"
            )

        await self.stop_system()
        self.teardown_scenario()

    @staticmethod
    def _expected_outputs(reference_date: datetime) -> dict[str, str]:
        week_start_day = 0  # Monday
        days_since_start = (reference_date.weekday() - week_start_day) % 7
        week_start = reference_date - timedelta(days=days_since_start)

        values = {
            "today": reference_date.strftime("%Y-%m-%d"),
            "yesterday": (reference_date - timedelta(days=1)).strftime("%Y-%m-%d"),
            "tomorrow": (reference_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "this-week": week_start.strftime("%Y-%m-%d"),
            "last-week": (week_start - timedelta(weeks=1)).strftime("%Y-%m-%d"),
            "next-week": (week_start + timedelta(weeks=1)).strftime("%Y-%m-%d"),
            "this-month": reference_date.strftime("%Y-%m"),
            "last-month": (reference_date.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
            "day-name": reference_date.strftime("%A"),
            "month-name": reference_date.strftime("%B"),
        }

        outputs = {
            f"outputs/{key}-{value}.md": f"Header {value}" for key, value in values.items()
        }

        formatted = {
            "today-compact": reference_date.strftime("%Y%m%d"),
            "this-week-compact": week_start.strftime("%Y%m%d"),
            "this-month-compact": reference_date.strftime("%Y%m"),
            "day-name-short": reference_date.strftime("%a"),
            "month-name-short": reference_date.strftime("%b"),
        }
        outputs.update(
            {
                f"outputs/{key}-{value}.md": f"Header {value}"
                for key, value in formatted.items()
            }
        )
        return outputs


PATTERN_SUBSTITUTION_WORKFLOW = """---
workflow_engine: step
enabled: false
week_start_day: monday
description: Validate pattern substitutions in @output and @header.
---

## TODAY
@model test
@output file: outputs/today-{today}
@header Header {today}

Emit a test response.

## YESTERDAY
@model test
@output file: outputs/yesterday-{yesterday}
@header Header {yesterday}

Emit a test response.

## TOMORROW
@model test
@output file: outputs/tomorrow-{tomorrow}
@header Header {tomorrow}

Emit a test response.

## THIS_WEEK
@model test
@output file: outputs/this-week-{this-week}
@header Header {this-week}

Emit a test response.

## LAST_WEEK
@model test
@output file: outputs/last-week-{last-week}
@header Header {last-week}

Emit a test response.

## NEXT_WEEK
@model test
@output file: outputs/next-week-{next-week}
@header Header {next-week}

Emit a test response.

## THIS_MONTH
@model test
@output file: outputs/this-month-{this-month}
@header Header {this-month}

Emit a test response.

## LAST_MONTH
@model test
@output file: outputs/last-month-{last-month}
@header Header {last-month}

Emit a test response.

## DAY_NAME
@model test
@output file: outputs/day-name-{day-name}
@header Header {day-name}

Emit a test response.

## MONTH_NAME
@model test
@output file: outputs/month-name-{month-name}
@header Header {month-name}

Emit a test response.

## TODAY_FORMATTED
@model test
@output file: outputs/today-compact-{today:YYYYMMDD}
@header Header {today:YYYYMMDD}

Emit a test response.

## THIS_WEEK_FORMATTED
@model test
@output file: outputs/this-week-compact-{this-week:YYYYMMDD}
@header Header {this-week:YYYYMMDD}

Emit a test response.

## THIS_MONTH_FORMATTED
@model test
@output file: outputs/this-month-compact-{this-month:YYYYMM}
@header Header {this-month:YYYYMM}

Emit a test response.

## DAY_NAME_FORMATTED
@model test
@output file: outputs/day-name-short-{day-name:ddd}
@header Header {day-name:ddd}

Emit a test response.

## MONTH_NAME_FORMATTED
@model test
@output file: outputs/month-name-short-{month-name:MMM}
@header Header {month-name:MMM}

Emit a test response.
"""
