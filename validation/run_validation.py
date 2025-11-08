#!/usr/bin/env python3
"""
CLI entry point for validation execution.

Provides command-line interface for running validation scenarios
with enhanced evidence collection and user-focused reporting.
"""

import sys
import argparse
from pathlib import Path

# Add project root to path FIRST
sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.core.runner import ValidationRunner
from core.logger import UnifiedLogger

logger = UnifiedLogger(tag="validation-cli")


def expand_scenario_paths(runner, scenario_specs):
    """
    Expand scenario specifications to full scenario names.

    Supports:
    - Individual scenarios: "basic_haiku" or "integration/basic_haiku"
    - Folders: "integration" expands to all scenarios in that folder
    """
    expanded = []
    all_scenarios = runner.discover_scenarios()

    for spec in scenario_specs:
        # Normalize path separators
        spec = spec.replace("\\", "/")

        # Check if this is an exact match for a scenario
        if spec in all_scenarios:
            expanded.append(spec)
            continue

        # Check if this is a folder containing scenarios
        folder_matches = [s for s in all_scenarios if s.startswith(f"{spec}/")]
        if folder_matches:
            expanded.extend(folder_matches)
            logger.info(f"Expanded folder '{spec}' to {len(folder_matches)} scenarios")
            continue

        # Not found - let it through and fail during execution with clear error
        logger.warning(f"No scenarios found matching '{spec}'")
        expanded.append(spec)

    return expanded


def run_scenarios(args):
    """Run validation scenarios."""
    runner = ValidationRunner()

    # Expand folder paths to individual scenarios
    scenario_names = expand_scenario_paths(runner, args.scenarios)

    if not scenario_names:
        logger.error("No scenarios to run")
        sys.exit(1)

    # Run scenarios
    validation_run = runner.run_scenarios(
        scenario_names=scenario_names,
    )
    
    # Print enhanced summary
    print("\n=== VALIDATION RUN COMPLETE ===")
    print(f"Run ID: {validation_run.run_id}")
    print(f"Total Scenarios: {validation_run.total_scenarios}")
    print(f"Passed: {validation_run.passed_scenarios}")
    print(f"Failed: {validation_run.failed_scenarios}")
    print(f"Errors: {validation_run.error_scenarios}")
    print(f"Success Rate: {validation_run.success_rate:.1f}%")
    
    # Print scenario details with enhanced formatting
    print("\n=== SCENARIO RESULTS ===")
    for result in validation_run.scenario_results:
        if result.status == "passed":
            status_symbol = "✅"
            status_text = "PASSED"
        elif result.status == "failed":
            status_symbol = "❌"
            status_text = "FAILED"
        elif result.status == "system_bug":
            status_symbol = "🚨"
            status_text = "SYSTEM ERROR"
        elif result.status == "framework_error":
            status_symbol = "💥"
            status_text = "FRAMEWORK ERROR"
        else:
            status_symbol = "❓"
            status_text = "ERROR"
        
        print(f"{status_symbol} {result.scenario_name} - {status_text} ({result.execution_time:.2f}s)")
        
        if result.error_message:
            print(f"   Error: {result.error_message}")
        
        # scenarios manage their own evidence in runs directory
        print("   Evidence: Check /app/validation/runs/ for scenario artifacts")
    
    # Additional V2-specific reporting
    if validation_run.error_scenarios > 0 or validation_run.failed_scenarios > 0:
        print("\n=== FOLLOW-UP ACTIONS ===")
        print("📋 Check individual scenario timelines in validation/runs/")
        print("🔍 Review vault snapshots for expected vs actual outputs")
        print("⚠️  Check validation/issues_log.md for tracked issues")
        
        if validation_run.error_scenarios > 0:
            print(f"🚨 CRITICAL: {validation_run.error_scenarios} system errors require immediate attention")
    
    # Exit with appropriate code
    sys.exit(0 if validation_run.failed_scenarios == 0 and validation_run.error_scenarios == 0 else 1)


def list_scenarios(args):
    """List available scenarios."""
    runner = ValidationRunner()
    scenarios = runner.discover_scenarios(pattern=args.pattern)

    print("=== AVAILABLE SCENARIOS ===")
    if scenarios:
        # Group scenarios by folder
        folders = {}
        for scenario in scenarios:
            if "/" in scenario:
                folder = scenario.rsplit("/", 1)[0]
                scenario_name = scenario.rsplit("/", 1)[1]
            else:
                folder = "(root)"
                scenario_name = scenario

            if folder not in folders:
                folders[folder] = []
            folders[folder].append((scenario, scenario_name))

        # Print grouped by folder
        for folder in sorted(folders.keys()):
            if folder == "(root)":
                print("\n📂 Root scenarios:")
            else:
                print(f"\n📂 {folder}/")

            for full_path, name in sorted(folders[folder], key=lambda x: x[1]):
                print(f"   • {name}")

        print(f"\n✨ Total: {len(scenarios)} scenarios available")
        print("\n💡 Usage:")
        print("   python validation/run_validation.py run basic_haiku          # Run single scenario")
        print("   python validation/run_validation.py run integration          # Run all scenarios in folder")
        print("   python validation/run_validation.py run integration experimental  # Run multiple folders")

    else:
        print("No scenarios found")
        if args.pattern:
            print(f"(No scenarios matching pattern: {args.pattern})")
        print("\n🚀 To create a scenario:")
        print("   1. Add a .py file to validation/scenarios/ (or subfolder)")
        print("   2. Create a class that inherits from BaseScenario")
        print("   3. Implement the test_scenario() method")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run validation scenarios for the AssistantMD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Validation Framework - User-focused scenario testing

Examples:
      python validation/run_validation.py run                    # Run all scenarios
  python validation/run_validation.py run weekly_planning daily_journaling
  python validation/run_validation.py list                        # List available scenarios

Features:
  ✅ Real assistant files in scenario folders
  ✅ High-level, readable scenario code  
  ✅ Comprehensive evidence collection
  ✅ User workflow focus vs feature testing
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run validation scenarios')
    run_parser.add_argument(
        'scenarios',
        nargs='+',
        help='One or more scenario names to run',
    )
    
    # List command
    list_parser = subparsers.add_parser('list', help='List available scenarios')
    list_parser.add_argument('--pattern', 
                            help='Pattern to filter scenarios by name')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Run the appropriate command
    if args.command == 'run':
        run_scenarios(args)
    elif args.command == 'list':
        list_scenarios(args)


if __name__ == "__main__":
    main()
