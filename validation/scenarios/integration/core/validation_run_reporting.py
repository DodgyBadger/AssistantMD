"""Validate failure-focused terminal and durable run reporting."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from validation.core.base_scenario import BaseScenario
from validation.core.reporting import render_terminal_summary, write_run_reports
from validation.core.results import ErrorClassification, ScenarioResult, ValidationRun
from validation.core.runner import ValidationRunner


class ValidationRunReportingScenario(BaseScenario):
    """Validate summaries make failures immediately actionable."""

    async def test_scenario(self):
        evidence = self.run_path / "synthetic-failure"
        timeline = evidence / "artifacts" / "timeline.md"
        timeline.parent.mkdir(parents=True)
        timeline.write_text("# Synthetic failure timeline\n", encoding="utf-8")

        validation_run = self._synthetic_run(evidence)
        summary = render_terminal_summary(
            validation_run,
            show_passed=False,
            report_paths=None,
        )
        verbose_summary = render_terminal_summary(
            validation_run,
            show_passed=True,
            report_paths=None,
        )

        self.soft_assert(
            "integration/core/passing_example" not in summary,
            "The default summary should collapse passing scenario details",
        )
        self.soft_assert(
            "integration/core/passing_example" in verbose_summary,
            "The verbose summary should include passing scenario details",
        )
        self.soft_assert(
            "=== FAILURES AND ERRORS (3) ===" in summary,
            "The final summary should expose the number of actionable results",
        )
        self.soft_assert(
            str(evidence) in summary and str(timeline) in summary,
            "Failure output should point directly to evidence and its timeline",
        )
        self.soft_assert(
            "uv run python validation/run_validation.py run integration/core/failing_example"
            in summary,
            "Each failure should include a copy/paste rerun command",
        )
        self.soft_assert(
            summary.rstrip().endswith(
                "uv run python validation/run_validation.py run "
                "integration/core/failing_example "
                "integration/core/system_example "
                "integration/core/framework_example"
            ),
            "The combined failure rerun should be the final terminal output",
        )

        report_paths = write_run_reports(
            validation_run,
            self.run_path / "report-output",
            retention=2,
        )
        report_payload = json.loads(report_paths.json.read_text(encoding="utf-8"))
        self.soft_assert_equal(
            report_payload["schema_version"],
            1,
            "The machine-readable report should publish its schema version",
        )
        self.soft_assert_equal(
            report_payload["failed_selectors"],
            [
                "integration/core/failing_example",
                "integration/core/system_example",
                "integration/core/framework_example",
            ],
            "The report should retain focused failure selectors",
        )
        self.soft_assert_equal(
            report_paths.latest_json.read_text(encoding="utf-8"),
            report_paths.json.read_text(encoding="utf-8"),
            "The latest JSON pointer should match the current report",
        )
        self.soft_assert(
            "## Failures and errors (3)"
            in report_paths.markdown.read_text(encoding="utf-8"),
            "The Markdown report should put failures before its complete summary",
        )

        missing_root = self.run_path / "missing-scenario-root"
        (missing_root / "scenarios").mkdir(parents=True)
        missing_run = ValidationRunner(missing_root).run_scenarios(
            ["integration/core/not_real"],
            requested_scenarios=["integration/core/not_real"],
        )
        self.soft_assert_equal(
            missing_run.scenario_results[0].status,
            "framework_error",
            "An unmatched selector should become a reportable framework error",
        )

        self.teardown_scenario()
        self.assert_no_failures()

    @staticmethod
    def _synthetic_run(evidence: Path) -> ValidationRun:
        started = datetime(2026, 8, 5, 12, 0, 0)
        failure_classification = ErrorClassification(
            type="SCENARIO FAILURE",
            status="failed",
            severity="low",
            recommendation="Review scenario assertions and expected outputs",
            emoji="❌",
        )
        system_classification = ErrorClassification(
            type="SYSTEM ERROR",
            status="system_bug",
            severity="high",
            recommendation="Review the captured stack trace",
            emoji="🚨",
        )
        framework_classification = ErrorClassification(
            type="FRAMEWORK ERROR",
            status="framework_error",
            severity="medium",
            recommendation="Check validation setup and dependencies",
            emoji="💥",
        )
        results = [
            ScenarioResult("integration/core/passing_example", "passed", 0.5),
            ScenarioResult(
                "integration/core/failing_example",
                "failed",
                1.0,
                error_message=(
                    "Scenario execution error: AssertionError: expected artifact\n"
                    "Failure location: /tmp/example.py:42 (in test_scenario)"
                ),
                error_classification=failure_classification,
                evidence_path=str(evidence),
                stack_trace="synthetic assertion trace",
            ),
            ScenarioResult(
                "integration/core/system_example",
                "system_bug",
                1.5,
                error_message="Scenario execution error: ValueError: bad state",
                error_classification=system_classification,
                evidence_path=str(evidence),
                stack_trace="synthetic system trace",
            ),
            ScenarioResult(
                "integration/core/framework_example",
                "framework_error",
                2.0,
                error_message="Scenario execution error: OSError: setup unavailable",
                error_classification=framework_classification,
                evidence_path=str(evidence),
                stack_trace="synthetic framework trace",
            ),
        ]
        return ValidationRun(
            run_id="20260805_120000_000000",
            start_time=started,
            end_time=started + timedelta(seconds=5),
            total_scenarios=4,
            passed_scenarios=1,
            failed_scenarios=1,
            error_scenarios=2,
            success_rate=25.0,
            scenario_results=results,
            requested_scenarios=["integration/core"],
            expanded_scenarios=[result.scenario_name for result in results],
        )
